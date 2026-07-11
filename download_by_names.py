#!/usr/bin/env python3
"""Download images from a Google Drive folder by providing basenames (no extension).

Reads a newline-separated list of basenames from a names file and downloads
the highest-quality matching files from the specified Drive folder.

Auth: service account JSON specified by `GOOGLE_SERVICE_ACCOUNT_FILE` in env
or passed via `--service-account-file`.
"""
import os
import io
import re
import argparse
import logging
from collections import defaultdict

from dotenv import load_dotenv
from google.oauth2 import service_account
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def load_names(names_file):
    with open(names_file, encoding="utf-8") as f:
        names = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    return names


def build_service(service_account_file=None, service_account_json=None, use_oauth=False, client_secrets_file=None, token_file=None):
    """Build Drive service using either a service account or OAuth user credentials.

    If `use_oauth` is True, `client_secrets_file` must point to OAuth client JSON.
    The resulting credentials are cached in `token_file` (default 'token.json').

    If `service_account_json` is provided, it may be the raw JSON string stored in an env var.
    """
    if use_oauth:
        token_file = token_file or os.getenv("OAUTH_TOKEN_FILE", "token.json")
        creds = None
        try:
            from google.oauth2.credentials import Credentials as OAuthCredentials
        except Exception:
            raise

        if os.path.exists(token_file):
            creds = OAuthCredentials.from_authorized_user_file(token_file, SCOPES)
        else:
            if not client_secrets_file or not os.path.exists(client_secrets_file):
                logger.error("OAuth client secrets file not found: %s", client_secrets_file)
                raise SystemExit(1)
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
            creds = flow.run_local_server(port=0)
            # save token
            with open(token_file, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())

        return build("drive", "v3", credentials=creds, cache_discovery=False)

    # service account JSON content
    if service_account_json is not None:
        if isinstance(service_account_json, str):
            try:
                info = json.loads(service_account_json)
            except json.JSONDecodeError:
                service_account_json = service_account_json.replace("\\n", "\n")
                info = json.loads(service_account_json)
        else:
            info = service_account_json
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    # service account path
    if not service_account_file or not os.path.exists(service_account_file):
        logger.error("Service account file not provided or not found: %s", service_account_file)
        raise SystemExit(1)
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_folder_files(service, folder_id):
    # Recursively list files in folder and its subfolders (BFS).
    files = []
    queue = [folder_id]
    fields = "nextPageToken, files(id, name, mimeType, size)"
    while queue:
        current = queue.pop(0)
        page_token = None
        q = f"'{current}' in parents and trashed = false"
        while True:
            res = (
                service.files()
                .list(q=q, spaces="drive", fields=fields, pageToken=page_token, pageSize=1000,
                      includeItemsFromAllDrives=True, supportsAllDrives=True)
                .execute()
            )
            for f in res.get("files", []):
                mime = f.get("mimeType", "")
                # If it's a folder, add to queue to traverse its children
                if mime == "application/vnd.google-apps.folder":
                    queue.append(f.get("id"))
                else:
                    files.append(f)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    return files


def parse_drive_folder_id(link_or_id):
    candidate = str(link_or_id).strip()
    if not candidate:
        raise ValueError("Drive folder link or ID is required")

    if "drive.google.com" in candidate:
        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", candidate)
        if match:
            return match.group(1)
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", candidate)
        if match:
            return match.group(1)
        raise ValueError("Unable to extract Drive folder ID from link")

    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", candidate):
        return candidate

    raise ValueError("Invalid Google Drive folder link or folder ID")


def list_folder_children(service, folder_id):
    children = []
    page_token = None
    q = f"'{folder_id}' in parents and trashed = false"
    while True:
        response = (
            service.files()
            .list(q=q, spaces="drive", fields="nextPageToken, files(id, name, mimeType, size)", pageToken=page_token,
                  includeItemsFromAllDrives=True, supportsAllDrives=True)
            .execute()
        )
        children.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return children


def download_drive_folder(service, folder_id, output_dir):
    folder_meta = service.files().get(fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True).execute()
    if folder_meta.get("mimeType") != "application/vnd.google-apps.folder":
        raise ValueError("Provided ID is not a Drive folder")

    root_name = folder_meta.get("name") or folder_id
    root_dir = os.path.join(output_dir, root_name)
    os.makedirs(root_dir, exist_ok=True)

    stats = {
        "downloaded": 0,
        "skipped": [],
        "errors": [],
        "root_folder": root_name,
    }

    def _download_children(current_folder_id, current_path):
        children = list_folder_children(service, current_folder_id)
        for child in children:
            name = child.get("name")
            mime = child.get("mimeType", "")
            if mime == "application/vnd.google-apps.folder":
                next_dir = os.path.join(current_path, name)
                os.makedirs(next_dir, exist_ok=True)
                _download_children(child["id"], next_dir)
                continue

            if mime.startswith("application/vnd.google-apps"):
                stats["skipped"].append(name)
                continue

            if download_file(service, child, current_path):
                stats["downloaded"] += 1
            else:
                stats["errors"].append(name)

    _download_children(folder_id, root_dir)
    return stats


def find_folders_by_path(service, root_folder_id, components):
    """Given path components, return list of folder ids matching the chain under root.

    If multiple folders share the same name at any level, this will explore all matches.
    """
    current_ids = [root_folder_id]
    for comp in components:
        comp = comp.strip()
        next_ids = []
        for cid in current_ids:
            page_token = None
            safe_comp = comp.replace("'", "\\'")
            q = (
                "name = '{}' and mimeType = 'application/vnd.google-apps.folder' "
                "and '{}' in parents and trashed = false".format(safe_comp, cid)
            )
            while True:
                res = (
                    service.files()
                    .list(q=q, spaces="drive", fields="nextPageToken, files(id, name)", pageToken=page_token,
                          includeItemsFromAllDrives=True, supportsAllDrives=True)
                    .execute()
                )
                for f in res.get("files", []):
                    next_ids.append(f.get("id"))
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
        current_ids = next_ids
        if not current_ids:
            return []
    return current_ids


def is_image_file(file_meta):
    name = file_meta.get("name", "").lower()
    mime = file_meta.get("mimeType", "")
    if mime.startswith("image/"):
        return True
    for ext in (".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".tif", ".tiff", ".bmp"):
        if name.endswith(ext):
            return True
    return False


def choose_best_file(candidates):
    # Prefer largest by size; size may be missing -> treat as 0
    def size_of(f):
        s = f.get("size")
        try:
            return int(s) if s is not None else 0
        except Exception:
            return 0

    best = max(candidates, key=size_of)
    return best


def download_file(service, file_meta, out_dir):
    file_id = file_meta["id"]
    name = file_meta["name"]
    mime = file_meta.get("mimeType", "")
    out_path = os.path.join(out_dir, name)
    os.makedirs(out_dir, exist_ok=True)

    if mime.startswith("application/vnd.google-apps"):
        logger.warning("Skipping native Google Drive file type: %s", name)
        return False

    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.FileIO(out_path, mode="wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    try:
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info("Downloading %s: %d%%", name, int(status.progress() * 100))
        logger.info("Saved %s", out_path)
        return True
    except Exception as e:
        logger.error("Failed to download %s: %s", name, e)
        return False


def download_by_names_file(
    names_file,
    output_dir,
    folder_id,
    service_account_file,
    service_account_json=None,
    use_oauth=False,
    client_secrets_file=None,
    token_file="token.json",
):
    if not folder_id:
        raise ValueError("DRIVE_FOLDER_ID is required")
    if not service_account_file and service_account_json is None:
        raise ValueError("Service account credentials are required")
    if service_account_file and not os.path.exists(service_account_file):
        raise FileNotFoundError(f"Service account file not found: {service_account_file}")
    if not os.path.exists(names_file):
        raise FileNotFoundError(f"Names file not found: {names_file}")

    names = load_names(names_file)
    if not names:
        raise ValueError(f"No names to download found in {names_file}")

    service = build_service(
        service_account_file=service_account_file,
        service_account_json=service_account_json,
        use_oauth=use_oauth,
        client_secrets_file=client_secrets_file,
        token_file=token_file,
    )
    logger.info("Listing files in Drive folder %s...", folder_id)
    files = list_folder_files(service, folder_id)

    by_base = defaultdict(list)
    for f in files:
        base = os.path.splitext(f.get("name", ""))[0]
        by_base[base].append(f)

    total = 0
    not_found = []
    downloaded_ids = set()

    for entry in names:
        if '->' in entry or '/' in entry:
            if '->' in entry:
                comps = [c.strip() for c in entry.split('->') if c.strip()]
            else:
                comps = [c.strip() for c in entry.split('/') if c.strip()]

            target_folders = find_folders_by_path(service, folder_id, comps)
            if not target_folders:
                logger.warning("Path not found: %s", entry)
                not_found.append(entry)
                continue

            found_any = False
            for tfid in target_folders:
                files_in_folder = list_folder_files(service, tfid)
                image_files = [f for f in files_in_folder if is_image_file(f)]
                if not image_files:
                    continue
                found_any = True
                for f in image_files:
                    fid = f.get('id')
                    if fid in downloaded_ids:
                        continue
                    if download_file(service, f, output_dir):
                        downloaded_ids.add(fid)
                        total += 1

            if not found_any:
                logger.warning("No image files found at path: %s", entry)
                not_found.append(entry)
            continue

        candidates = by_base.get(entry)
        if not candidates:
            logger.warning("No file matching basename: %s", entry)
            not_found.append(entry)
            continue
        best = choose_best_file(candidates)
        fid = best.get('id')
        if fid in downloaded_ids:
            logger.info("Already downloaded: %s", best.get('name'))
            continue
        if download_file(service, best, output_dir):
            downloaded_ids.add(fid)
            total += 1

    logger.info("Done. Downloaded %d/%d requested items.", total, len(names))
    return {
        "downloaded": total,
        "requested": len(names),
        "not_found": not_found,
    }


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Download Drive images by basename list")
    parser.add_argument("--names-file", default=os.getenv("NAMES_FILE", "names.txt"))
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "downloads"))
    parser.add_argument("--folder-id", default=os.getenv("DRIVE_FOLDER_ID"))
    parser.add_argument(
        "--service-account-file", default=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    )
    parser.add_argument("--service-account-json", default=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"), help="Raw service account JSON from environment")
    parser.add_argument("--use-oauth", action="store_true", help="Use OAuth user consent flow instead of service account")
    parser.add_argument("--client-secrets", default=os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS"), help="Path to OAuth client_secrets JSON")
    parser.add_argument("--token-file", default=os.getenv("OAUTH_TOKEN_FILE", "token.json"), help="Path to cache OAuth token JSON")
    args = parser.parse_args()

    try:
        result = download_by_names_file(
            args.names_file,
            args.output_dir,
            args.folder_id,
            args.service_account_file,
            service_account_json=args.service_account_json,
            use_oauth=args.use_oauth,
            client_secrets_file=args.client_secrets,
            token_file=args.token_file,
        )
    except Exception as exc:
        logger.error(str(exc))
        return

    logger.info("Downloaded %d/%d requested items.", result["downloaded"], result["requested"])
    if result["not_found"]:
        print("\nNot found entries:")
        for n in result["not_found"]:
            print(n)


if __name__ == "__main__":
    main()
