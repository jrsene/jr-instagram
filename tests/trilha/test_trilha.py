"""Testes da trilha dos reels: a trilha gerada passa; ruído e tom puro são recusados.
Rodar: python -m tests.trilha.test_trilha  (precisa de numpy e ffmpeg)"""
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autopost import trilha  # noqa: E402


def _gravar(p: Path, x: np.ndarray):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(trilha.SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def main():
    T = 40 * trilha.SR
    t = np.arange(T) / trilha.SR
    rng = np.random.default_rng(1)
    casos = {
        "trilha calma gerada": (trilha.gerada(), True),
        "tom puro antigo (220+330 Hz)": (None, False),
        "ruído branco": (None, False),
        "ruído marrom": (None, False),
    }
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        x = 0.13 * np.sin(2 * np.pi * 220 * t) + 0.09 * np.sin(2 * np.pi * 330 * t)
        _gravar(d / "seno.wav", x)
        _gravar(d / "branco.wav", rng.normal(0, 0.1, T))
        marrom = np.cumsum(rng.normal(0, 1, T))
        _gravar(d / "marrom.wav", (marrom - marrom.mean()) / np.abs(marrom).max() * 0.5)
        caminhos = {"tom puro antigo (220+330 Hz)": d / "seno.wav", "ruído branco": d / "branco.wav",
                    "ruído marrom": d / "marrom.wav"}
        falhas = 0
        for nome, (caminho, esperado) in casos.items():
            caminho = caminho or caminhos[nome]
            ok, motivo = trilha.verificar(caminho, 10)
            resultado = "OK" if ok == esperado else "FALHOU"
            falhas += ok != esperado
            print(f"{resultado}: {nome} -> {ok} ({motivo})")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
