"""Guarda o estado (catálogo, cópias reduzidas e posts ainda não publicados) criptografado.

O repositório é público, então nada pessoal pode ir em texto aberto: data/ e output/ viram um único
arquivo state.enc, legível só com a chave STATE_KEY (segredo do GitHub).
Cópias vindas do OneDrive (data/cache/od_*) ficam de fora, porque podem ser rebaixadas a qualquer hora.

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


def pack():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for d in ("data", "output"):
            p = ROOT / d
            if p.exists():
                tar.add(p, arcname=d, filter=lambda t: None if "/cache/od_" in t.name else t)
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
