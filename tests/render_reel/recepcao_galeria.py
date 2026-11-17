"""Teste manual: folhas com fotos de recepção (balcões, entradas, áreas de entrada) de todos os álbuns.

Cada foto sai com o nome do álbum embaixo. Não publica nada e não monta reel.
Uso: python tests/render_reel/recepcao_galeria.py <pasta_de_saida>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "render_reel"))

import yaml  # noqa: E402
from autopost import library, site  # noqa: E402
from duas_por_album import conferencia  # noqa: E402

PALAVRAS = ("recep", "balc", "entrada", "hall", "espera", "lobby", "portaria", "acesso", "fachada")
POR_FOLHA = 12
POR_ALBUM = 4


def recepcao(r) -> bool:
    texto = f"{r['album'] or ''} {r['tags'] or ''} {r['path'] or ''}".lower()
    return any(p in texto for p in PALAVRAS)


def main(saida: str) -> int:
    out = Path(saida)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    db = library.connect(ROOT)
    linhas = []
    log = lambda m: (linhas.append(str(m)), print(m, flush=True))
    log(f"galeria: {site.sync(db, cfg, log=log)} nova(s)")
    rows = db.execute("select * from media where kind='image' and ok=1 and score>=0.6"
                      " order by album, id").fetchall()
    grupos = {}
    for r in rows:
        if recepcao(r):
            grupos.setdefault(r["album"] or "avulsas", []).append(r)
    escolhidas = []
    for album in sorted(grupos):
        escolhidas += grupos[album][:POR_ALBUM]
    rel = {"candidatas": len(escolhidas), "albuns": len(grupos), "folhas": []}
    for i in range(0, len(escolhidas), POR_FOLHA):
        nome = f"recepcao_{i // POR_FOLHA + 1}.jpg"
        conferencia(escolhidas[i:i + POR_FOLHA], out / nome,
                    rotulo=lambda r: (r["album"] or "avulsa")[-40:] + f" · {r['path'][-10:]}")
        rel["folhas"].append(nome)
    if not escolhidas:
        log("nenhuma foto de recepção encontrada pelas palavras-chave")
    rel["log"] = linhas[-40:]
    (out / "recepcao.json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in rel.items() if k != "log"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "resultados"))
