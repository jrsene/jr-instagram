"""Narração com a voz do Junior nos reels (clonagem de voz local, de graça, sem crédito).

Usa o Chatterbox Multilingual (código aberto, roda na própria máquina do GitHub, fala português).
A amostra da voz (10 a 30 s de você falando) vem da pasta do OneDrive "jr-instagram/voz", fica em data/voz/
e vai criptografada no state.enc, nunca aberta no repositório. Sem amostra, o reel sai só com música.
"""
import subprocess
from pathlib import Path

from . import library

_model = {"m": None}


def amostra() -> Path | None:
    d = library.ROOT / "data" / "voz"
    files = sorted(p for p in d.glob("*") if p.suffix.lower() in {".wav", ".m4a", ".mp3", ".ogg", ".aac"}) if d.exists() else []
    if not files:
        return None
    ref = d / "_ref.wav"
    if not ref.exists() or ref.stat().st_mtime < files[-1].stat().st_mtime:
        # mono 24 kHz, até 30 s, sem silêncio no começo
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(files[-1]), "-t", "30", "-ac", "1", "-ar", "24000",
                        "-af", "silenceremove=start_periods=1:start_threshold=-45dB", str(ref)], check=True)
    return ref


def ativo(cfg) -> bool:
    return bool((cfg.get("narracao") or {}).get("ativo")) and amostra() is not None


def falar(texto: str, cfg, out: Path, log=print) -> Path | None:
    """Gera a narração em out (.wav). Devolve None se não der (sem amostra, sem motor instalado etc.)."""
    if not texto or not ativo(cfg):
        return None
    try:
        import torchaudio
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        if _model["m"] is None:
            _model["m"] = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        m = _model["m"]
        nc = cfg.get("narracao", {})
        wav = m.generate(texto, language_id=nc.get("idioma", "pt"), audio_prompt_path=str(amostra()),
                         exaggeration=nc.get("expressividade", 0.5))
        torchaudio.save(str(out), wav, m.sr)
        return out
    except Exception as e:
        log(f"  ! narração indisponível ({type(e).__name__}: {e}); reel só com música")
        return None
