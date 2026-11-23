"""Trilha sonora dos reels: música calma de verdade, com verificação antes de usar.

Ordem de escolha: os mp3 de assets/music (se houver), depois uma trilha calma gerada aqui (acordes suaves,
sem batida). Toda trilha passa por verificar(): se não for música (ruído, tom puro, mudo, estourado ou curta
demais), é recusada. Se nenhuma passar, o reel não sai.
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import library

SR = 22050
LOOP_S = 32.0
# quatro acordes de 8 s, em Hz (C maj7, Am7, Fmaj7, G)
ACORDES = [
    [261.63, 329.63, 392.00, 493.88],
    [220.00, 261.63, 329.63, 392.00],
    [174.61, 220.00, 261.63, 329.63],
    [196.00, 246.94, 293.66, 392.00],
]


def _soma(buf, inicio_s, x):
    """Soma x no buffer circular a partir de inicio_s: o que passa do fim volta ao começo (loop sem emenda)."""
    i0 = int(round(inicio_s * SR))
    idx = (np.arange(len(x)) + i0) % len(buf)
    buf[idx] += x


def _gerar_pcm() -> np.ndarray:
    n = int(LOOP_S * SR)
    buf = np.zeros(n)
    for k, notas in enumerate(ACORDES):
        ini = k * 8.0
        for f in notas:  # pad: ataque lento, sustentado e soltando sobre o acorde seguinte
            t = np.arange(int(10 * SR)) / SR
            env = np.minimum(1.0, t / 2.5) * np.exp(-np.maximum(0.0, t - 6.0) / 1.5)
            tom = 0.6 * np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t) + 0.08 * np.sin(2 * np.pi * 3 * f * t)
            _soma(buf, ini, tom * env * 0.05)
        for j in range(8):  # sinos suaves, um a cada segundo, notas do acorde uma oitava acima
            f = notas[(j * 3) % len(notas)] * 2
            t = np.arange(int(2.5 * SR)) / SR
            tom = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 4)
            _soma(buf, ini + j + 0.5, tom * np.exp(-t * 2.2) * 0.035)
    # reverberação leve (atrasos circulares, cabem no loop)
    buf = buf + 0.3 * np.roll(buf, int(0.31 * SR)) + 0.18 * np.roll(buf, int(0.53 * SR))
    buf = buf - np.mean(buf)
    rms = np.sqrt(np.mean(buf ** 2))
    buf = buf * (0.10 / rms)  # ~ -20 dBFS de média
    return np.clip(buf, -0.9, 0.9)


def gerada() -> Path:
    """Trilha calma gerada uma vez e guardada em data/ (fora do git)."""
    caminho = library.ROOT / "data" / "trilha_calma_v1.wav"
    if not caminho.exists():
        caminho.parent.mkdir(parents=True, exist_ok=True)
        pcm = (_gerar_pcm() * 32767).astype("<i2")
        with wave.open(str(caminho), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
    return caminho


def _ler(caminho: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(caminho), "-vn", "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64) / 32768


def verificar(caminho: Path, minimo_s: float) -> tuple[bool, str]:
    """(ok, motivo). Recusa: arquivo que não abre, curto, mudo, estourado, ruído (sem picos de nota)
    e tom puro (energia concentrada em uma ou duas frequências)."""
    try:
        x = _ler(caminho)
    except Exception as e:
        return False, f"não abre ({type(e).__name__})"
    dur = len(x) / SR
    if dur < minimo_s:
        return False, f"curta ({dur:.0f} s, precisa de {minimo_s:.0f})"
    db = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)
    if db < -40 or db > -10:
        return False, f"volume fora da faixa ({db:.0f} dBFS)"
    if np.max(np.abs(x)) >= 0.999:
        return False, "estourado (clipagem)"
    N = 2048
    quadros = np.lib.stride_tricks.sliding_window_view(x, N)[::N // 2]
    S = np.abs(np.fft.rfft(quadros * np.hanning(N), axis=1)) ** 2
    f = np.fft.rfftfreq(N, 1 / SR)
    M = S[:, (f >= 80) & (f <= 4000)].mean(0)
    mediana = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(M, 15, mode="edge"), 31), axis=1)
    picos = M > 3 * mediana  # notas: frequências que sobressaem do fundo
    # conta trechos contínuos de pico (cada nota ou harmônico forma um)
    trechos = int(np.sum(np.diff(np.concatenate([[0], picos.astype(int)])) == 1))
    if trechos < 8:
        return False, f"sem notas (ruído: só {trechos} picos de frequência)"
    if M.sum() > 0 and np.sort(M)[-3:].sum() / M.sum() > 0.5:
        return False, "tom puro (energia concentrada em poucas frequências)"
    return True, f"ok ({dur:.0f} s, {db:.0f} dBFS, {trechos} notas)"


def escolher(cfg: dict, log=print) -> Path | None:
    """Primeira trilha válida: mp3 de assets/music, depois a calma gerada. None = nenhuma serve.
    A trilha toca em loop (-stream_loop), então só precisa ser uma música de verdade, não ter a duração do reel."""
    pasta = library.ROOT / cfg.get("visual", {}).get("musica_pasta", "assets/music")
    candidatas = sorted(pasta.glob("*.mp3")) if pasta.exists() else []
    candidatas.append(gerada())
    for c in candidatas:
        ok, motivo = verificar(c, 10)
        if ok:
            log(f"  trilha: {c.name} ({motivo})")
            return c
        log(f"  trilha {c.name} recusada: {motivo}")
    return None
