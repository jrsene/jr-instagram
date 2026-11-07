"""Teste de bancada (não faz parte do piloto): compara a transcrição com tempo por palavra (stable-ts e
faster-whisper) e separa a voz do fundo com demucs, nos clipes de tests/audio_spike/clipes/.
Roda no GitHub Actions pelo workflow 'teste-audio' (manual). Não publica nada."""
import json
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "resultados")
CLIPES = Path(__file__).parent / "clipes"
OUT.mkdir(parents=True, exist_ok=True)
relatorio = {}


def tempo(nome, fn):
    t = time.time()
    try:
        r = fn()
        relatorio[nome] = {"segundos": round(time.time() - t, 1), **(r or {})}
    except Exception as e:  # um teste quebrado não derruba os outros
        relatorio[nome] = {"erro": f"{type(e).__name__}: {str(e)[:300]}", "segundos": round(time.time() - t, 1)}
    print(nome, relatorio[nome], flush=True)


def stable(clipe):
    import stable_whisper
    m = stable_whisper.load_faster_whisper("small", device="cpu", compute_type="int8")
    r = m.transcribe(str(clipe), language="pt", word_timestamps=True, vad=True)
    palavras = [(w.start, w.end, w.word.strip()) for s in r.segments for w in s.words if w.word.strip()]
    (OUT / f"{clipe.stem}_stable.json").write_text(json.dumps(palavras, ensure_ascii=False, indent=1))
    return {"palavras": len(palavras), "primeiras": " ".join(p[2] for p in palavras[:12])}


def faster(clipe):
    from faster_whisper import WhisperModel
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(clipe), language="pt", word_timestamps=True, vad_filter=True)
    palavras = [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]
    (OUT / f"{clipe.stem}_faster.json").write_text(json.dumps(palavras, ensure_ascii=False, indent=1))
    return {"palavras": len(palavras), "primeiras": " ".join(p[2] for p in palavras[:12])}


def demucs(clipe):
    subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "-d", "cpu",
                    "-o", str(OUT / "demucs"), str(clipe)], check=True, capture_output=True)
    vocais = list((OUT / "demucs").rglob("vocals.wav"))
    return {"vocais": str(vocais[0].name) if vocais else None}


clipes = sorted(CLIPES.glob("*.wav"))
for c in clipes:
    tempo(f"stable-ts {c.stem}", lambda c=c: stable(c))
    tempo(f"faster-whisper {c.stem}", lambda c=c: faster(c))
    tempo(f"demucs {c.stem}", lambda c=c: demucs(c))
(OUT / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1))
print(json.dumps(relatorio, ensure_ascii=False, indent=1))
