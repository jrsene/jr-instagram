"""Teste manual de render de reel: não publica nada e não usa segredos.

Gera dois clipes sintéticos (só máquina, e com fala em português sobre máquina),
passa cada um pelo compose.video_reel com a transcrição de verdade (faster-whisper)
e guarda os reels e um relatório.json na pasta de saída.

Uso: python tests/render_reel/render.py <pasta_de_saida>
"""
import json
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from autopost import compose  # noqa: E402


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def probe(p: Path) -> dict:
    o = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height:format=duration", "-of", "json", str(p)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(o)


def gera_clipes(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    fala = pasta / "fala.wav"
    subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "150", "-w", str(fala),
                    "Essa obra ficou muito bonita. O acabamento do piso e da parede ficou perfeito."],
                   check=True)
    # 1) só máquina: 8 s de ruído marrom no lugar do som da obra
    ruido = pasta / "ruido.wav"
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=brown:amplitude=0.25:d=12",
           "-ar", "44100", "-ac", "2", str(ruido))
    # 2) fala sobre ruído: a fala entra aos 2 s, por cima da máquina
    mix = pasta / "fala_com_maquina.wav"
    ffmpeg("-i", str(ruido), "-i", str(fala),
           "-filter_complex", "[1:a]adelay=2000|2000,volume=1.5[f];[0:a][f]amix=inputs=2:duration=first:normalize=0",
           "-ar", "44100", "-ac", "2", str(mix))
    for nome, audio, dur in [("sem_fala", ruido, 8), ("com_fala", mix, 12)]:
        video = pasta / f"{nome}.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1080x1440:rate=30",
               "-i", str(audio), "-t", str(dur),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video))
        ffmpeg("-ss", "1", "-i", str(video), "-frames:v", "1", str(pasta / f"{nome}.jpg"))


def main(saida: str) -> int:
    out = Path(saida)
    out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    clipes = out / "clipes"
    gera_clipes(clipes)

    casos = [
        ("sem_fala", None),
        ("com_fala", {"albuns": [{"album": "teste"}], "arquiteto_txt": ["@arq"], "fotografo_txt": ["@foto"]}),
    ]
    relatorio, falhas = [], 0
    for nome, creditos in casos:
        linhas: list[str] = []

        def log(msg, _l=linhas):
            _l.append(str(msg))
            print(msg, flush=True)

        row = {"id": nome, "path": str(clipes / f"{nome}.mp4"), "cache": str(clipes / f"{nome}.jpg")}
        destino = out / f"reel_{nome}.mp4"
        entrada = {"caso": nome}
        try:
            compose.video_reel(row, destino, cfg=cfg, log=log,
                               texto="Acabamento que fala por si", creditos=creditos)
            info = probe(destino)
            video = [s for s in info["streams"] if s["codec_type"] == "video"]
            audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
            dur = float(info["format"]["duration"])
            minimo = float((cfg.get("video") or {}).get("duracao_min", 8))
            entrada.update({
                "duracao_s": round(dur, 2),
                "resolucao": f"{video[0]['width']}x{video[0]['height']}" if video else None,
                "fluxos_video": len(video),
                "fluxos_audio": len(audio),
                "ok": bool(video and audio and video[0]["width"] == 1080
                           and video[0]["height"] == 1920 and dur >= minimo - 0.1
                           and len(video) == 1),
            })
        except Exception as e:  # o relatório guarda o erro em vez de parar no meio
            falhas += 1
            entrada.update({"ok": False, "erro": f"{type(e).__name__}: {e}",
                            "rastro": traceback.format_exc()[-1500:]})
        entrada["log"] = linhas[-40:]
        relatorio.append(entrada)
        print(json.dumps({k: v for k, v in entrada.items() if k != "log"}, ensure_ascii=False), flush=True)

    (out / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    falhas += sum(1 for r in relatorio if not r.get("ok"))
    print(f"\n{len(relatorio) - falhas} de {len(relatorio)} reel(s) ok")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "resultados_reel"))
