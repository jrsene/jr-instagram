"""Guarda o estado (catálogo, cópias reduzidas e posts ainda não publicados) criptografado.

O repositório é público, então nada pessoal pode ir em texto aberto: data/ e output/ viram um único
arquivo state.enc, legível só com a chave STATE_KEY (segredo do GitHub).
Cópias vindas do OneDrive e do site (data/cache/od_*, site_*) ficam de fora, porque podem ser rebaixadas a qualquer hora.

  python -m autopost.state unpack   # antes de rodar
  python -m autopost.state pack     # depois de rodar
  python -m autopost.state key      # gera uma chave nova
"""
import io
import os
import sys
import tarfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state.enc"


def _key():
    return Fernet(os.environ["STATE_KEY"].encode())


def _keep_days(dias=2):
    """Dias de output/ que ainda importam: os recentes e os que têm post esperando aprovação/publicação.
    O resto (já publicado ou rascunho vencido) não precisa ir no state.enc, que fica pequeno."""
    from datetime import date, timedelta
    keep = {(date.today() - timedelta(days=i)).isoformat() for i in range(dias + 1)}
    db = ROOT / "data" / "library.db"
    if db.exists():
        import sqlite3
        con = sqlite3.connect(db)
        try:
            keep |= {r[0] for r in con.execute(
                "select distinct substr(scheduled_for,1,10) from posts where status in ('pendente','aprovado','pronto')"
                " or scheduled_for >= date('now')")}
        finally:
            con.close()
    return keep


def pack():
    keep = _keep_days()

    def skip(t):
        parts = t.name.split("/")
        if "/cache/od_" in t.name or "/cache/site_" in t.name:  # rebaixáveis da nuvem/site
            return None
        if parts[0] == "output" and len(parts) > 1 and parts[1][:4].isdigit() and parts[1] not in keep:
            return None
        return t

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for d in ("data", "output"):
            p = ROOT / d
            if p.exists():
                tar.add(p, arcname=d, filter=skip)
    STATE.write_bytes(_key().encrypt(buf.getvalue()))
    print(f"estado salvo ({STATE.stat().st_size // 1024} KB)")


def unpack():
    if not STATE.exists():
        print("sem estado anterior, começando do zero")
        return
    raw = _key().decrypt(STATE.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(ROOT, filter="data")
    print("estado restaurado")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "key":
        print(Fernet.generate_key().decode())
    elif cmd in ("pack", "unpack"):
        globals()[cmd]()
    else:
        print(__doc__)
