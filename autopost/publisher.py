"""Publicação via API oficial do Instagram (Graph API). Só roda fora do modo dry_run."""
import base64
import os
import time
from pathlib import Path

import requests


class Publisher:
    def __init__(self, cfg: dict, root: Path):
        ig = cfg.get("instagram", {})
        self.cfg, self.root = ig, root
        self.base = f"{ig.get('api_base', 'https://graph.instagram.com').rstrip('/')}/{ig.get('api_versao', 'v23.0')}"
        self.user = os.environ.get("IG_USER_ID")
        self.token = self._load_token()
        if not (self.user and self.token):
            raise RuntimeError("Faltam IG_USER_ID e IG_ACCESS_TOKEN nas variáveis de ambiente.")
        self._maybe_refresh()

    # O token do Instagram vale 60 dias. Renovamos sozinhos a cada ~7 dias e guardamos criptografado.
    def _tok_file(self):
        return self.root / "data" / "ig_token.enc"

    def _load_token(self):
        key = os.environ.get("STATE_KEY")
        if key and self._tok_file().exists():
            from cryptography.fernet import Fernet
            return Fernet(key.encode()).decrypt(self._tok_file().read_bytes()).decode()
        return os.environ.get("IG_ACCESS_TOKEN")

    def _maybe_refresh(self):
        key = os.environ.get("STATE_KEY")
        f = self._tok_file()
        if not key or "graph.instagram.com" not in self.base:
            return
        if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
            return
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": self.token}, timeout=30)
        if r.ok and r.json().get("access_token"):
            from cryptography.fernet import Fernet
            self.token = r.json()["access_token"]
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(Fernet(key.encode()).encrypt(self.token.encode()))

    # ---------- hospedagem pública dos arquivos ----------
    def public_url(self, path: Path) -> str:
        mode = self.cfg.get("hospedagem", "github")
        rel = path.relative_to(self.root / "output").as_posix()
        if mode == "url_prefix":
            return f"{self.cfg['url_prefix'].rstrip('/')}/{rel}"
        if mode == "github":
            repo, tok = os.environ["GH_REPO"], os.environ["GH_TOKEN"]
            api = f"https://api.github.com/repos/{repo}/contents/media/{rel}"
            h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
            sha = requests.get(api, headers=h, timeout=30).json().get("sha")
            body = {"message": f"media {rel}", "content": base64.b64encode(path.read_bytes()).decode()}
            if sha:
                body["sha"] = sha
            r = requests.put(api, headers=h, json=body, timeout=120)
            r.raise_for_status()
            return r.json()["content"]["download_url"]
        raise ValueError(f"hospedagem desconhecida: {mode}")

    # ---------- Graph API ----------
    def _post(self, path, **params):
        params["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", data=params, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"Instagram {r.status_code}: {r.text[:400]}")
        return r.json()

    def _wait(self, cid, tries=60):
        for _ in range(tries):
            r = requests.get(f"{self.base}/{cid}", params={"fields": "status_code", "access_token": self.token},
                             timeout=30).json()
            if r.get("status_code") == "FINISHED":
                return
            if r.get("status_code") == "ERROR":
                raise RuntimeError(f"processamento falhou: {r}")
            time.sleep(5)
        raise TimeoutError("Instagram demorou demais para processar a mídia")

    def _container(self, file: Path, **extra):
        key = "video_url" if file.suffix == ".mp4" else "image_url"
        cid = self._post(f"{self.user}/media", **{key: self.public_url(file)}, **extra)["id"]
        self._wait(cid)
        return cid

    def publish(self, ptype: str, files: list[Path], caption: str, alt: str = "") -> str:
        if ptype == "story":
            mt = "STORIES"
            cid = self._container(files[0], media_type=mt)
        elif ptype == "reel":
            cid = self._container(files[0], media_type="REELS", caption=caption, share_to_feed="true")
        elif len(files) > 1:
            kids = [self._container(f, is_carousel_item="true",
                                    **({"media_type": "VIDEO"} if f.suffix == ".mp4" else {})) for f in files]
            cid = self._post(f"{self.user}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption)["id"]
            self._wait(cid)
        else:
            extra = {"alt_text": alt} if alt else {}
            cid = self._container(files[0], caption=caption, **extra)
        return self._post(f"{self.user}/media_publish", creation_id=cid)["id"]
