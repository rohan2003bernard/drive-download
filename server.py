import os
from pathlib import Path
from typing import Optional
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from download_by_names import (
    download_by_names_file,
    parse_drive_folder_id,
    build_service,
    download_drive_folder,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = Path(os.getenv("OUTPUT_DIR", "downloads"))
SERVICE_ACCOUNT_FILE = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "client_secrets.json"))
FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
ALLOWED_EXTENSIONS = {"txt"}

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Drive Image Downloader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_batch_output_dir(prefix: str, target_path: Optional[str] = None) -> Path:
    base_dir = Path(target_path).expanduser() if target_path else OUTPUT_FOLDER
    base_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = base_dir / f"{prefix}_{uuid4().hex[:8]}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir


def list_files_for_manifest(root_dir: Path) -> list[dict]:
    return [
        {"path": file_path.relative_to(root_dir).as_posix(), "name": file_path.name}
        for file_path in sorted(root_dir.rglob("*"))
        if file_path.is_file()
    ]


@app.post("/api/upload")
async def upload_names(file: UploadFile = File(...), target_path: Optional[str] = Form(None)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if not file.filename or not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Only .txt files are allowed")

    if not FOLDER_ID:
        raise HTTPException(status_code=500, detail="DRIVE_FOLDER_ID is not configured in .env")
    if not SERVICE_ACCOUNT_FILE.exists():
        raise HTTPException(status_code=500, detail=f"Service account file not found: {SERVICE_ACCOUNT_FILE}")

    upload_path = UPLOAD_FOLDER / Path(file.filename).name
    contents = await file.read()
    upload_path.write_bytes(contents)

    batch_dir = create_batch_output_dir(f"upload_{Path(file.filename).stem}", target_path=target_path)
    try:
        result = download_by_names_file(
            names_file=str(upload_path),
            output_dir=str(batch_dir),
            folder_id=FOLDER_ID,
            service_account_file=str(SERVICE_ACCOUNT_FILE),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "message": "Upload received and download started",
        "result": result,
        "files": list_files_for_manifest(batch_dir),
        "batch": batch_dir.name,
        "output_directory": str(batch_dir.resolve()),
    }


@app.post("/api/copy-folder")
async def copy_folder(payload: Optional[dict] = Body(None)):
    if not payload:
        raise HTTPException(status_code=400, detail="Request body is required")

    link = payload.get("link")
    if not link:
        raise HTTPException(status_code=400, detail="Drive folder link is required")

    folder_id = parse_drive_folder_id(link)
    if not SERVICE_ACCOUNT_FILE.exists():
        raise HTTPException(status_code=500, detail=f"Service account file not found: {SERVICE_ACCOUNT_FILE}")

    service = build_service(service_account_file=str(SERVICE_ACCOUNT_FILE))
    target_path = payload.get("target_path") if payload else None
    batch_dir = create_batch_output_dir("drive_folder", target_path=target_path)
    try:
        result = download_drive_folder(service, folder_id, str(batch_dir))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "message": "Folder copied to local storage",
        "result": result,
        "files": list_files_for_manifest(batch_dir),
        "batch": batch_dir.name,
        "output_directory": str(batch_dir.resolve()),
    }


@app.get("/api/download-file")
async def download_file(path: str, batch: str):
    batch_dir = OUTPUT_FOLDER / batch
    if not batch_dir.exists():
        raise HTTPException(status_code=404, detail="Batch not found")

    requested_path = (batch_dir / path).resolve()
    if not str(requested_path).startswith(str(batch_dir.resolve())) or not requested_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        requested_path,
        media_type="application/octet-stream",
        filename=requested_path.name,
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
