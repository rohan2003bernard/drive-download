# Drive image downloader

Quick script and server to download images from a Google Drive folder by providing basenames (without extensions).

## Setup

1. Copy `.env.example` to `.env` and fill `GOOGLE_SERVICE_ACCOUNT_FILE` and `DRIVE_FOLDER_ID`.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Command-line usage

Place a newline-separated list of basenames (no extension) in `names.txt` or change `NAMES_FILE` in `.env`.

Run:

```bash
python download_by_names.py --service-account-file path/to/service-account.json --folder-id YOUR_FOLDER_ID
```

Or rely on `.env` values:

```bash
python download_by_names.py
```

## Server usage

The backend is now a FastAPI app and the frontend is a Next.js app.

1. Make sure `.env` contains valid values:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=client_secrets.json
DRIVE_FOLDER_ID=YOUR_FOLDER_ID
OUTPUT_DIR=downloads
NEXT_PUBLIC_API_URL=http://localhost:8000
```

2. Start the backend server:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

3. Start the frontend app:

```bash
cd frontend
npm install
npm run dev
```

4. Open the frontend in a browser:

```text
http://localhost:3000
```
If the app is hosted remotely, use:

```text
https://tfgkbl1w-3000.inc1.devtunnels.ms/
```

The backend API base URL is:

```text
https://dork-egotism-alive.ngrok-free.dev/
```
5. Upload your `.txt` file with one name per line on the main page.

### Copy folder page

Navigate to `/copy-folder` or click the link from the homepage to provide a Google Drive folder link/ID.

- The frontend sends the folder link to `/api/copy-folder`.
- The backend copies the Drive folder contents recursively into the local `downloads/` folder.

### What happens

- `/api/upload` accepts a `.txt` file upload and downloads matching Drive images.
- `/api/copy-folder` accepts a Drive folder link or ID and copies all files from that folder.

## Output

Downloaded files are saved in the `downloads/` folder by default.

## Frontend

The frontend is a Next.js app in `frontend/`.

## Notes

- Only `.txt` uploads are accepted.
- The server runs on port `5000` and binds to `0.0.0.0` so it can be accessed from another machine on the same network.
- Ensure your firewall allows incoming traffic on port `5000`.

## OAuth option

1. Create OAuth client credentials: Go to Google Cloud Console → APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app. Download the JSON and save as `client_secrets.json`.
2. Either set `GOOGLE_OAUTH_CLIENT_SECRETS=client_secrets.json` in `.env` or pass `--client-secrets client_secrets.json`.
3. Run with `--use-oauth` the first time; a browser window will open for consent. The token will be saved to `token.json` (or `OAUTH_TOKEN_FILE` env var).

## Examples

- Service account (recommended for shared folders):

```bash
python download_by_names.py --service-account-file path/to/service-account.json --folder-id YOUR_FOLDER_ID
```

- Server:

```bash
python server.py
```

Then visit `http://<SERVER_IP>:5000/` from your other system.
