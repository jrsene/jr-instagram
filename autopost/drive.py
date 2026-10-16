"""Puxa fotos e vídeos novos de pastas do Google Drive para inbox/drive/.

Usa uma conta de serviço do Google (JSON na variável GDRIVE_SA_JSON). Basta compartilhar
a(s) pasta(s) com o e-mail dessa conta como "Leitor".
"""
import io
import json
import os
from pathlib import Path

MEDIA = ("image/", "video/")


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GDRIVE_SA_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _walk(svc, folder_id):
    q = f"'{folder_id}' in parents and trashed = false"
    token = None
    while True:
        r = svc.files().list(q=q, pageToken=token, pageSize=200, supportsAllDrives=True,
                             includeItemsFromAllDrives=True,
                             fields="nextPageToken, files(id,name,mimeType,size)").execute()
        for f in r.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                yield from _walk(svc, f["id"])
            elif f["mimeType"].startswith(MEDIA):
                yield f
        token = r.get("nextPageToken")
        if not token:
            return


def sync(root: Path, cfg: dict, log=print) -> int:
    folders = cfg.get("drive", {}).get("pastas", [])
    if not folders or not os.environ.get("GDRIVE_SA_JSON"):
        return 0
    from googleapiclient.http import MediaIoBaseDownload
    svc = _service()
    dest = root / "inbox" / "drive"
    dest.mkdir(parents=True, exist_ok=True)
    state_f = root / "data" / "drive_state.json"
    seen = set(json.loads(state_f.read_text())) if state_f.exists() else set()
    max_mb = cfg.get("drive", {}).get("max_mb", 300)
    n = 0
    for folder in folders:
        for f in _walk(svc, folder):
            if f["id"] in seen or int(f.get("size", 0)) > max_mb * 1e6:
                continue
            out = dest / f"{f['id'][:8]}_{f['name']}"
            with open(out, "wb") as fh:
                dl = MediaIoBaseDownload(fh, svc.files().get_media(fileId=f["id"], supportsAllDrives=True))
                done = False
                while not done:
                    _, done = dl.next_chunk()
            seen.add(f["id"])
            n += 1
            log(f"  ↓ {f['name']}")
    state_f.parent.mkdir(exist_ok=True)
    state_f.write_text(json.dumps(sorted(seen)))
    return n
