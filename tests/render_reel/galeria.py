"""Teste manual: monta um reel só com fotos da galeria do site, sem publicar nada.

Sincroniza a galeria (leitura pública), escolhe fotos com a mesma regra do piloto,
monta o reel com compose.reel e confere a duração. Não usa segredos nem toca no Instagram.

Uso: python tests/render_reel/galeria.py <pasta_de_saida>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from autopost import compose, library, site  # noqa: E402


def main(saida: str) -> int:
    out = Path(saida)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    resultado = {"etapas": [], "ok": False}
    linhas = []

    def log(msg):
        linhas.append(str(msg))
        print(msg, flush=True)

    db = library.connect(ROOT)
    novas = site.sync(db, cfg, log=log)
    total = db.execute("select count(*) from media").fetchone()[0]
    resultado["etapas"].append({"galeria_sincronizada": novas, "midias_no_catalogo": total})

    rows = library.pick(db, cfg, 15, group_by_day=True)
    resultado["fotos_escolhidas"] = len(rows)
    if len(rows) < 3:
        resultado["motivo"] = "fotos insuficientes na galeria para montar um reel"
    else:
        destino = out / "reel_galeria.mp4"
        try:
            compose.reel(rows, cfg, destino, music=None, voice=None, falado="")
            info = subprocess_probe(destino)
            resultado.update(info)
            resultado["ok"] = info["duracao_s"] >= 30 - 0.1
        except Exception as e:  # o relatório guarda o erro
            resultado["erro"] = f"{type(e).__name__}: {e}"
    resultado["log"] = linhas[-60:]
    (out / "relatorio.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in resultado.items() if k != "log"}, ensure_ascii=False, indent=2))
    return 0 if resultado["ok"] else 1


def subprocess_probe(p: Path) -> dict:
    import subprocess
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True, check=True).stdout
    d = json.loads(o)
    video = [s for s in d["streams"] if s["codec_type"] == "video"]
    return {"duracao_s": round(float(d["format"]["duration"]), 2),
            "resolucao": f"{video[0]['width']}x{video[0]['height']}" if video else None}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "resultados_galeria"))
