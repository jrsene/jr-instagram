"""Edição automática de vídeos falados: corta as pausas e coloca legenda no tempo de cada fala.

Transcrição com faster-whisper (código aberto, roda local). Sem ele, o vídeo segue sem cortes nem legenda.
"""
import json
import subprocess
from pathlib import Path

_model = {"m": None}


def duracao(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def transcrever(src: Path, cfg, log=print) -> list[tuple[float, float, str]]:
    """Palavras faladas com início e fim (s). Lista vazia se não houver fala ou motor."""
    try:
        from faster_whisper import WhisperModel
        if _model["m"] is None:
            ec = cfg.get("edicao", {})
            _model["m"] = WhisperModel(ec.get("modelo_fala", "small"), device="cpu", compute_type="int8")
        segs, info = _model["m"].transcribe(str(src), language=cfg.get("narracao", {}).get("idioma", "pt"),
                                            word_timestamps=True, vad_filter=True)
        return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]
    except Exception as e:
        log(f"  ! transcrição indisponível ({type(e).__name__}: {e})")
        return []


def trechos_com_fala(words, total: float, pausa=0.6, folga=0.15) -> list[tuple[float, float]]:
    """Junta as palavras em trechos, cortando silêncios maiores que `pausa`."""
    keep: list[list[float]] = []
    for a, b, _ in words:
        a, b = max(0.0, a - folga), min(total, b + folga)
        if keep and a - keep[-1][1] <= pausa:
            keep[-1][1] = max(keep[-1][1], b)
        else:
            keep.append([a, b])
    return [(a, b) for a, b in keep]


def remapear(words, trechos):
    """Novos tempos das palavras depois de cortar as pausas."""
    out, base = [], 0.0
    for a, b in trechos:
        for s, e, w in words:
            if s >= a and e <= b + 0.01:
                out.append((base + s - a, base + e - a, w))
        base += b - a
    return out


def cortar(src: Path, out: Path, trechos, vf: str) -> Path:
    """Mantém só os trechos (vídeo + áudio) e aplica o filtro de vídeo final vf."""
    parts, labels = [], ""
    for i, (a, b) in enumerate(trechos):
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels += f"[v{i}][a{i}]"
    fc = ";".join(parts) + f";{labels}concat=n={len(trechos)}:v=1:a=1[vc][ac];[vc]{vf}[vo]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", fc, "-map", "[vo]", "-map", "[ac]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-movflags", "+faststart",
                    str(out)], check=True)
    return out


def _t(s: float) -> str:
    h, r = divmod(max(0.0, s), 3600)
    m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def legenda_ass(words, path: Path, size=(1080, 1920), por_bloco=3, fonte="Inter") -> Path:
    """Legenda estilo reels: blocos de até 3 palavras, grandes, centralizadas, palavra falada em destaque."""
    W, H = size
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Fala,{fonte},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,{int(H * 0.22)},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    for i in range(0, len(words), por_bloco):
        bloco = words[i:i + por_bloco]
        fim_bloco = words[i + por_bloco][0] if i + por_bloco < len(words) else bloco[-1][1] + 0.3
        for j, (s, e, _) in enumerate(bloco):
            fim = bloco[j + 1][0] if j + 1 < len(bloco) else fim_bloco
            txt = " ".join(("{\\c&H00D7FF&\\fscx108\\fscy108}" + w.upper() + "{\\r}") if k == j else w.upper()
                           for k, (_, _, w) in enumerate(bloco))
            lines.append(f"Dialogue: 0,{_t(s)},{_t(fim)},Fala,,0,0,0,,{txt}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def palavras_no_tempo(texto: str, inicio: float, dur: float):
    """Para a narração gerada: espalha as palavras pelo tempo da fala, proporcional ao tamanho de cada uma."""
    ws = texto.split()
    if not ws:
        return []
    peso = [len(w) + 2 for w in ws]
    tot, t, out = sum(peso), inicio, []
    for w, p in zip(ws, peso):
        d = dur * p / tot
        out.append((t, t + d, w))
        t += d
    return out
