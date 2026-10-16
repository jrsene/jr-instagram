"""Fonte OneDrive: lê o 'Álbum da Câmera' (Upload da Câmera do iPhone) pela Microsoft Graph.

Não baixa os originais pesados: guarda uma cópia de 1800px (versão reduzida gerada pelo próprio OneDrive, mantém a proporção),
que já serve para posts e stories. Vídeos só são baixados quando forem escolhidos para um reel.

Login uma única vez:  python -m autopost onedrive-login
No GitHub: rode o workflow 'conectar-onedrive'. Só precisa do segredo ONEDRIVE_CLIENT_ID; o token fica
criptografado em data/onedrive_token.enc (dentro do state.enc), nunca em texto aberto.
"""
import json
import os
import random
import time
from pathlib import Path

import requests
from PIL import Image

from . import library

GRAPH = "https://graph.microsoft.com/v1.0"
AUTH = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPES = "Files.Read offline_access"
_token = {"v": None, "exp": 0}


# ---------------- autenticação ----------------
def _token_file():
    return library.ROOT / "data" / "onedrive_token.enc"


def _fernet_key():
    return os.environ.get("ONEDRIVE_KEY") or os.environ.get("STATE_KEY")


def _stored_refresh():
    key = _fernet_key()
    f = _token_file()
    if key and f.exists():
        from cryptography.fernet import Fernet
        return Fernet(key.encode()).decrypt(f.read_bytes()).decode()
    return os.environ.get("ONEDRIVE_REFRESH_TOKEN")


def _save_refresh(tok):
    key = _fernet_key()
    if key:
        from cryptography.fernet import Fernet
        _token_file().parent.mkdir(exist_ok=True)
        _token_file().write_bytes(Fernet(key.encode()).encrypt(tok.encode()))


def access_token():
    if _token["v"] and time.time() < _token["exp"]:
        return _token["v"]
    r = requests.post(f"{AUTH}/token", data={
        "client_id": os.environ["ONEDRIVE_CLIENT_ID"], "grant_type": "refresh_token",
        "refresh_token": _stored_refresh(), "scope": SCOPES}, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("refresh_token"):
        _save_refresh(d["refresh_token"])
    _token.update(v=d["access_token"], exp=time.time() + d.get("expires_in", 3600) - 120)
    return _token["v"]


def login():
    """Login pelo celular/navegador com código (device code). Imprime o que cadastrar no GitHub."""
    cid = os.environ.get("ONEDRIVE_CLIENT_ID") or input("ONEDRIVE_CLIENT_ID: ").strip()
    d = requests.post(f"{AUTH}/devicecode", data={"client_id": cid, "scope": SCOPES}, timeout=30).json()
    print(d["message"])
    while True:
        time.sleep(d.get("interval", 5))
        r = requests.post(f"{AUTH}/token", data={
            "client_id": cid, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": d["device_code"]}, timeout=30).json()
        if "refresh_token" in r and _fernet_key():
            # rodando no GitHub: guarda o token criptografado, sem nunca imprimir
            _save_refresh(r["refresh_token"])
            print("OneDrive conectado e token guardado com segurança.")
            return
        if "refresh_token" in r:
            from cryptography.fernet import Fernet
            print("\nCadastre estes segredos no GitHub (Settings → Secrets → Actions):")
            print(f"ONEDRIVE_CLIENT_ID = {cid}")
            print(f"ONEDRIVE_REFRESH_TOKEN = {r['refresh_token']}")
            print(f"ONEDRIVE_KEY = {Fernet.generate_key().decode()}")
            return
        if r.get("error") not in ("authorization_pending", "slow_down"):
            raise SystemExit(f"falhou: {r}")


def _get(url, **kw):
    for attempt in range(4):
        r = requests.get(url if url.startswith("http") else f"{GRAPH}{url}",
                         headers={"Authorization": f"Bearer {access_token()}"}, timeout=120, **kw)
        if r.status_code in (429, 503):
            time.sleep(int(r.headers.get("Retry-After", 5 * (attempt + 1))))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()


# ---------------- leitura ----------------
def _walk(item_id):
    url = f"/me/drive/items/{item_id}/children?$top=200&$select=id,name,file,folder,photo,video,image,size,createdDateTime"
    while url:
        d = _get(url).json()
        for it in d.get("value", []):
            if "folder" in it:
                yield from _walk(it["id"])
            elif "file" in it and it["file"].get("mimeType", "").startswith(("image/", "video/")):
                yield it
        url = d.get("@odata.nextLink")


def _fetch_thumb(item_id, dest: Path, size=1800):
    r = _get(f"/me/drive/items/{item_id}/thumbnails/0/{size}x{size}/content")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)


def _fetch(row, dest: Path, video: bool):
    item = row["path"].split(":", 1)[1]
    if video:
        tmp = dest.with_suffix(".orig")
        with _get(f"/me/drive/items/{item}/content", stream=True) as r, open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-t", "60", "-vf",
                        "scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)'",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac",
                        "-movflags", "+faststart", str(dest)], check=True)
        tmp.unlink()
    else:
        _fetch_thumb(item, dest)


library.FETCHERS["onedrive"] = _fetch


def sync(db, cfg: dict, log=print) -> int:
    oc = cfg.get("onedrive", {})
    if not oc.get("ativo") or not os.environ.get("ONEDRIVE_CLIENT_ID") or not _stored_refresh():
        return 0
    roots = []
    for pasta in oc.get("pastas", ["cameraroll"]):
        url = f"/me/drive/special/{pasta}" if pasta == "cameraroll" else f"/me/drive/root:/{pasta}"
        roots.append(_get(url).json()["id"])
    known = {r["path"] for r in db.execute("select path from media where path like 'onedrive:%'")}
    new = [it for root in roots for it in _walk(root) if f"onedrive:{it['id']}" not in known]

    def taken(it):
        return (it.get("photo") or {}).get("takenDateTime") or it["createdDateTime"]

    new.sort(key=taken, reverse=True)
    # por execução: as mais recentes + uma amostra do arquivo antigo (para ir "garimpando" o passado)
    lim = oc.get("por_execucao", 40)
    recent, old = new[:lim * 3 // 4], new[lim * 3 // 4:]
    batch = recent + random.sample(old, min(len(old), lim - len(recent)))
    cache_dir = library.ROOT / "data" / "cache"
    added = 0
    for it in batch:
        fid = "od_" + it["id"].replace("!", "_")[-24:]
        cache = cache_dir / f"{fid}.jpg"
        try:
            _fetch_thumb(it["id"], cache)
            im = Image.open(cache).convert("RGB")
            is_vid = it["file"]["mimeType"].startswith("video/")
            dur = (it.get("video") or {}).get("duration", 0) / 1000 if is_vid else None
            if is_vid and (dur or 0) < 2:
                continue
            if not library.add_media(db, fid, f"onedrive:{it['id']}", "video" if is_vid else "image",
                                     taken(it)[:19], im.width, im.height, dur,
                                     0.7 if is_vid else library.quality(im), cache):
                # repetida: registra só para não reavaliar, fora da rotação
                db.execute("insert or ignore into media(id,path,kind,ok,motivo) values(?,?,?,0,'repetida')",
                           (fid, f"onedrive:{it['id']}", "image"))
                cache.unlink(missing_ok=True)
                continue
            added += 1
            log(f"  ☁ {it['name']}")
        except Exception as e:
            log(f"  ! {it['name']}: {e}")
    db.commit()
    log(f"  OneDrive: {len(new) - added} ainda na fila para as próximas execuções")
    return added
