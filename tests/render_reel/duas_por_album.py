"""Teste manual: reel de fotos em transição com 2 fotos por álbum, sem publicar nada.

Regra do pedido (16/11): duas fotos por álbum, as mais amplas (mais abertura). Fotos de piscina
são de dia (as mais claras). Trilha: assets/music/comfy_fundo.mp3 (livre de direitos).
Uso: python tests/render_reel/duas_por_album.py <pasta_de_saida>
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from PIL import Image, ImageStat  # noqa: E402
from autopost import compose, library, site  # noqa: E402

TRILHA = ROOT / "assets" / "music" / "comfy_fundo.mp3"


def luz(r) -> float:
    im = Image.open(library.local(r)).convert("L")
    im.thumbnail((200, 200))
    return ImageStat.Stat(im).mean[0]


def piscina(r) -> bool:
    return "piscina" in f"{r['album'] or ''} {r['tags'] or ''}".lower()


def escolher(db) -> list:
    rows = db.execute("select * from media where kind='image' and ok=1 and score>=0.75").fetchall()
    grupos = {}
    for r in rows:
        grupos.setdefault(r["album"] or "avulsas", []).append(r)
    escolhidas = []
    for album in sorted(grupos):
        fotos = grupos[album]
        if any(piscina(r) for r in fotos):
            fotos = sorted(fotos, key=lambda r: (luz(r), (r["w"] or 1) / (r["h"] or 1)), reverse=True)
        else:
            fotos = sorted(fotos, key=lambda r: ((r["w"] or 1) / (r["h"] or 1), r["score"]), reverse=True)
        escolhidas += fotos[:2]
    return escolhidas


def conferencia(rows, destino: Path) -> None:
    """Folha de conferência: as fotos escolhidas em grade, com o álbum escrito embaixo de cada uma."""
    from PIL import ImageDraw, ImageFont
    cols, lado, rot = 3, 360, 26
    linhas = (len(rows) + cols - 1) // cols
    folha = Image.new("RGB", (cols * lado, linhas * (lado + rot)), (244, 239, 232))
    fonte = ImageFont.load_default(size=18) if hasattr(ImageFont, "load_default") else ImageFont.load_default()
    for i, r in enumerate(rows):
        im = Image.open(library.local(r)).convert("RGB")
        im.thumbnail((lado - 10, lado - 10))
        x, y = (i % cols) * lado, (i // cols) * (lado + rot)
        folha.paste(im, (x + (lado - im.width) // 2, y + (lado - im.height) // 2))
        ImageDraw.Draw(folha).text((x + 8, y + lado + 4), str(r["album"] or "avulsa")[:40], fill=(40, 40, 40), font=fonte)
    folha.save(destino, quality=88)


def main(saida: str) -> int:
    out = Path(saida)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    linhas = []
    log = lambda m: (linhas.append(str(m)), print(m, flush=True))
    db = library.connect(ROOT)
    log(f"galeria: {site.sync(db, cfg, log=log)} nova(s)")
    rows = escolher(db)
    for r in rows:  # lista as fotos escolhidas, para o dono conferir antes de montar de novo
        ratio = (r["w"] or 1) / (r["h"] or 1)
        log(f"escolhida: álbum={r['album']} | arquivo={r['path']} | proporção={ratio:.2f} | piscina={piscina(r)}")
    try:
        conferencia(rows, out / "conferencia.jpg")
    except Exception as e:
        log(f"conferencia: {type(e).__name__}: {e}")
    rel = {"fotos": len(rows), "albuns": len({r['album'] for r in rows}), "ok": False}
    if len(rows) < 2:
        rel["motivo"] = "fotos insuficientes"
    elif (31.0 + 0.4 * (len(rows) - 1)) / len(rows) > 4.5:
        rel["motivo"] = f"fotos insuficientes para 30 s com 2 por álbum ({len(rows)} fotos)"
    else:
        # 2 fotos por álbum; se forem poucas para 30 s, cada foto fica um pouco mais (sem repetir nem travar)
        # compose: total = por_foto*n - 0,4*(n-1) (transições). Para passar de 30 s, cada foto dura o necessário.
        por_foto = (31.0 + 0.4 * (len(rows) - 1)) / len(rows)
        if por_foto > 4.5:  # foto demais parada vira "slide show" lento; abaixo disso, sem reel
            rel["motivo"] = f"fotos insuficientes para 30 s com 2 por álbum ({len(rows)} fotos)"
        destino = out / "reel_duas_por_album.mp4"
        try:
            compose.reel(rows, cfg, destino, music=TRILHA, voice=None, falado="", per=por_foto)
            o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(destino)], capture_output=True, text=True, check=True).stdout
            rel["duracao_s"] = round(float(o.strip()), 2)
            rel["por_foto_s"] = round(por_foto, 2)
            rel["ok"] = rel["duracao_s"] >= 30 - 0.1
        except Exception as e:
            rel["erro"] = f"{type(e).__name__}: {e}"
    rel["log"] = linhas[-40:]
    (out / "relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in rel.items() if k != "log"}, ensure_ascii=False, indent=2))
    return 0 if rel["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "resultados"))
