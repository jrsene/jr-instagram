"""Teste manual: reel com as fotos confirmadas pelo dono (piscina de dia, fachada e recepção),
mais fotos dos mesmos álbuns até chegar a 30 s com conteúdo real. Não publica nada.
Uso: python tests/render_reel/reel_confirmadas.py <pasta_de_saida>
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "render_reel"))

import yaml  # noqa: E402
from autopost import compose, library, site  # noqa: E402
from duas_por_album import TRILHA, conferencia, luz, piscina  # noqa: E402

CONFIRMADAS = ("0-25-9tdv", "8-21-mr63lr", "4-14-au1l7")  # piscina de dia, fachada, recepção
EXTRAS_POR_ALBUM = 3  # fotos extras por álbum confirmado (além das confirmadas)


def main(saida: str) -> int:
    out = Path(saida)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    db = library.connect(ROOT)
    linhas = []
    log = lambda m: (linhas.append(str(m)), print(m, flush=True))
    log(f"galeria: {site.sync(db, cfg, log=log)} nova(s)")
    rows = db.execute("select * from media where kind='image' and ok=1 and score>=0.6 order by album, id").fetchall()
    escolhidas = []
    for suf in CONFIRMADAS:
        achou = [r for r in rows if r["path"].endswith(suf)]
        if not achou:
            log(f"não encontrei a foto confirmada {suf}")
            continue
        escolhidas.append(achou[0])
    albuns = {r["album"] for r in escolhidas}
    for album in sorted(albuns):
        grupo = [r for r in rows if r["album"] == album and r not in escolhidas]
        if any(piscina(r) for r in grupo):  # piscina: as mais claras (de dia)
            grupo = sorted(grupo, key=lambda r: (luz(r), (r["w"] or 1) / (r["h"] or 1)), reverse=True)
        else:
            grupo = sorted(grupo, key=lambda r: ((r["w"] or 1) / (r["h"] or 1), r["score"]), reverse=True)
        escolhidas += grupo[:EXTRAS_POR_ALBUM]
    for r in escolhidas:
        log(f"usada: álbum={r['album']} | arquivo={r['path']}")
    rel = {"fotos": len(escolhidas), "albuns": len(albuns), "ok": False}
    por_foto = (31.0 + 0.4 * (len(escolhidas) - 1)) / len(escolhidas)
    if len(escolhidas) < 3 or por_foto > 4.5:
        rel["motivo"] = f"fotos insuficientes para 30 s sem travar ({len(escolhidas)} fotos)"
    else:
        conferencia(escolhidas, out / "folha_confirmadas.jpg",
                    rotulo=lambda r: (r["album"] or "avulsa")[-30:] + f" · {r['path'][-10:]}")
        destino = out / "reel_confirmadas.mp4"
        try:
            compose.reel(escolhidas, cfg, destino, music=TRILHA, voice=None, falado="", per=por_foto)
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
