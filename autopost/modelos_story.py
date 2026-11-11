"""Modelos de story escolhidos pelo Junior no Canva (11/11/2026), refeitos aqui para sair no automático.

  galeria    (modelo 1): fundo grafite texturizado, título em serifa no alto, foto quadrada com borda
                         branca no meio, créditos e linha magenta embaixo.
  player     (modelo 3): vídeo. Fotos da obra passando em slide num cartão arredondado, com um painel
                         escuro embaixo e uma barra que vai crescendo até o fim, como música tocando.
                         Sem botões de play (o Junior não quis cara de player parado).
  editorial  (modelo 4): fundo escuro liso, foto larga em cima, logo, endereço do álbum em caixa alta
                         espaçada e o nome do projeto em serifa.

Os três respeitam a área segura do Instagram: nada nos 250 px do topo (foto e nome do perfil) nem
nos 340 px da base (barra de resposta).
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import compose, library

W, H = 1080, 1920
TOPO, BASE = 250, H - 340
MAGENTA = (229, 0, 90)
MODELOS = ["galeria", "player", "editorial"]
FPS = 24


def escolher(n: int) -> str:
    """Alterna os modelos: o story n usa MODELOS[n % 3]."""
    return MODELOS[n % len(MODELOS)]


# ---------- tipografia ----------

def _serif(size: int, peso: str = "Light") -> ImageFont.FreeTypeFont:
    f = library.ROOT / "assets" / "fonts" / "CormorantGaramond.ttf"
    try:
        font = ImageFont.truetype(str(f), size)
        try:
            font.set_variation_by_name(peso)
        except Exception:
            pass
        return font
    except Exception:
        for nome in ("DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"):
            try:
                return ImageFont.truetype(nome, size)
            except Exception:
                pass
    return ImageFont.load_default(size)


def _largura(d, texto, font, tracking=0.0):
    return d.textlength(texto, font=font) + tracking * max(0, len(texto) - 1)


def _texto(d, xy, texto, font, fill, tracking=0.0, centro=True):
    """Texto com espaçamento entre letras (tracking em px), centrado em x quando centro=True."""
    x, y = xy
    if centro:
        x -= _largura(d, texto, font, tracking) / 2
    if not tracking:
        d.text((x, y), texto, font=font, fill=fill)
        return
    for ch in texto:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + tracking


def _caber(d, texto, tamanhos, fonte, larg, tracking=0.0):
    """Primeira fonte em que o texto cabe numa linha; senão a menor, em até 2 linhas."""
    for s in tamanhos:
        f = fonte(s)
        if _largura(d, texto, f, tracking) <= larg:
            return f, [texto]
    f = fonte(tamanhos[-1])
    return f, compose._wrap(d, texto, f, larg)[:2]


def _creditos(c: dict) -> list[str]:
    arq = c.get("arquiteto_txt") or c.get("arquiteto") or []
    fot = c.get("fotografo_txt") or c.get("fotografo") or []
    out = []
    if arq:
        out.append(f"Arquitetura: {' e '.join(arq)}")
    if fot:
        out.append(f"Fotografia: {' e '.join(fot)}")
    return out


def _link(c: dict, cfg) -> str:
    if c.get("albuns") or c.get("arquiteto") or c.get("fotografo"):
        return c.get("link") or "jrobras.com/galeria"
    return cfg.get("perfil", {}).get("handle", "")


def _linha_cortada(d, texto, font, larg):
    while d.textlength(texto, font=font) > larg and len(texto) > 10:
        texto = texto[:-2].rstrip() + "…"
    return texto


def _logo_centro(canvas, y, altura=40):
    logo = compose._logo(altura)
    if logo:
        canvas.alpha_composite(logo, ((W - logo.width) // 2, y))
    return altura


def _textura(cor=(35, 35, 35), seed=7) -> Image.Image:
    """Fundo grafite com grão leve e cantos mais escuros (o 'concreto' do modelo 1)."""
    rng = np.random.default_rng(seed)
    ruido = rng.normal(0, 1, (H // 4, W // 4)).astype(np.float32)
    ruido = np.asarray(Image.fromarray(((ruido * 18) + 128).clip(0, 255).astype(np.uint8))
                       .resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2)), dtype=np.float32) - 128
    yy, xx = np.mgrid[0:H, 0:W]
    vinheta = 1 - 0.28 * (((xx / W - 0.5) ** 2) * 2 + ((yy / H - 0.5) ** 2) * 2)
    base = np.array(cor, dtype=np.float32)[None, None, :] * vinheta[..., None] + ruido[..., None] * 0.5
    return Image.fromarray(base.clip(0, 255).astype(np.uint8)).convert("RGBA")


# ---------- modelo 1: galeria ----------

def galeria(rows, cfg, text: str | None = None, creditos: dict | None = None) -> Image.Image:
    c = creditos or {}
    canvas = _textura()
    d = ImageDraw.Draw(canvas)
    y = TOPO + 14
    y += _logo_centro(canvas, y, 40) + 26
    d = ImageDraw.Draw(canvas)
    titulo = compose._limpa(text or (c.get("albuns") or [{}])[0].get("album") or "Obra concluída")
    f, linhas = _caber(d, titulo, (84, 72, 62), lambda s: _serif(s, "Light"), W - 160)
    for ln in linhas:
        _texto(d, (W / 2, y), ln, f, (255, 255, 255))
        y += round(f.size * 1.05)
    y += 22
    d.rectangle((W / 2 - 68, y, W / 2 + 67, y + 2), fill=MAGENTA)

    lado, borda = 790, 14
    foto = compose._polish(compose.smart_fit(compose._load(rows[0]), (lado, lado)))
    py = max(y + 44, 520)
    px = (W - lado) // 2
    d.rectangle((px - borda, py - borda, px + lado + borda - 1, py + lado + borda - 1), fill=(250, 250, 248))
    canvas.alpha_composite(foto.convert("RGBA"), (px, py))

    d = ImageDraw.Draw(canvas)
    y = py + lado + borda + 40
    fc = compose._font_peso(cfg, 24, "SemiBold")
    for ln in _creditos(c):
        _texto(d, (W / 2, y), _linha_cortada(d, ln, fc, W - 120), fc, (236, 234, 230))
        y += 38
    fl = compose._font_peso(cfg, 19, "SemiBold")
    link = _link(c, cfg).upper()
    if link:
        _texto(d, (W / 2, y + 8), link, fl, (190, 186, 180), tracking=3)
        y += 44
    d.rectangle((W / 2 - 292, min(y + 6, BASE - 10), W / 2 + 292, min(y + 8, BASE - 8)), fill=MAGENTA)
    return canvas.convert("RGB")


# ---------- modelo 4: editorial ----------

def editorial(rows, cfg, text: str | None = None, creditos: dict | None = None) -> Image.Image:
    c = creditos or {}
    canvas = Image.new("RGBA", (W, H), (31, 31, 31, 255))
    foto = compose._polish(compose.smart_fit(compose._load(rows[0]), (W - 46, 980)))
    canvas.alpha_composite(foto.convert("RGBA"), (23, TOPO))
    y = TOPO + 980 + 44
    y += _logo_centro(canvas, y, 40) + 26
    d = ImageDraw.Draw(canvas)
    link = _link(c, cfg).upper()
    if link:
        _texto(d, (W / 2, y), link, compose._font_peso(cfg, 19, "SemiBold"), (160, 158, 154), tracking=4)
        y += 46
    titulo = compose._limpa(text or (c.get("albuns") or [{}])[0].get("album") or "Obra concluída").upper()
    f, linhas = _caber(d, titulo, (60, 52, 44), lambda s: _serif(s, "Regular"), W - 140, tracking=5)
    for ln in linhas:
        _texto(d, (W / 2, y), ln, f, (255, 255, 255), tracking=5)
        y += round(f.size * 1.1)
    y += 18
    fc = compose._font_peso(cfg, 22, "SemiBold")
    for ln in _creditos(c):
        if y + 30 > BASE:
            break
        _texto(d, (W / 2, y), _linha_cortada(d, ln, fc, W - 120), fc, (200, 197, 192))
        y += 34
    return canvas.convert("RGB")


# ---------- modelo 3: player (vídeo) ----------

def _arredondado(im: Image.Image, raio: int) -> Image.Image:
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), raio, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m)
    return out


CARTAO = (93, TOPO, W - 93, 1196)          # x0, y0, x1, y1 do cartão da foto
PAINEL = (93, 1226, W - 93, BASE - 20)     # painel escuro com título, créditos e barra
BARRA_Y = PAINEL[3] - 76


def _cena(foto: Image.Image, zoom: float) -> Image.Image:
    """Fundo desfocado + cartão arredondado com a foto (zoom lento para dar movimento)."""
    cw, ch = CARTAO[2] - CARTAO[0], CARTAO[3] - CARTAO[1]
    bg = foto.resize((W // 6, H // 6)).filter(ImageFilter.GaussianBlur(4)).resize((W, H), Image.BILINEAR)
    bg = Image.blend(bg, Image.new("RGB", (W, H), (20, 20, 20)), 0.45).convert("RGBA")
    zw, zh = round(cw * zoom), round(ch * zoom)
    big = foto.resize((zw, zh), Image.BILINEAR)
    ox, oy = (zw - cw) // 2, (zh - ch) // 2
    card = _arredondado(big.crop((ox, oy, ox + cw, oy + ch)), 22)
    borda = _arredondado(Image.new("RGB", (cw + 10, ch + 10), (255, 255, 255)), 26)
    bg.alpha_composite(borda, (CARTAO[0] - 5, CARTAO[1] - 5))
    bg.alpha_composite(card, (CARTAO[0], CARTAO[1]))
    return bg


def _painel(cfg, text, c) -> Image.Image:
    p = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(p)
    d.rounded_rectangle(PAINEL, 17, fill=(47, 47, 47, 205))
    x, y, larg = PAINEL[0] + 40, PAINEL[1] + 30, PAINEL[2] - PAINEL[0] - 80
    logo = compose._logo(34)
    if logo:
        p.alpha_composite(logo, (x, y))
        d = ImageDraw.Draw(p)
        d.text((x + logo.width + 16, y + 9), "OBRAS CONCLUÍDAS", font=compose._font_peso(cfg, 17, "Bold"), fill=(201, 169, 106))
        y += 58
    titulo = compose._limpa(text or (c.get("albuns") or [{}])[0].get("album") or "Obra concluída")
    f, linhas = _caber(d, titulo, (46, 40, 34), lambda s: compose._font_peso(cfg, s, "Bold"), larg)
    d.text((x, y), _linha_cortada(d, linhas[0], f, larg), font=f, fill=(255, 255, 255))
    y += round(f.size * 1.3)
    fc = compose._font_peso(cfg, 26, "SemiBold")
    for ln in _creditos(c):
        if y + 30 > BARRA_Y - 10:
            break
        d.text((x, y), _linha_cortada(d, ln, fc, larg), font=fc, fill=(232, 230, 226))
        y += 36
    return p


def _barra(canvas: Image.Image, cfg, t: float, total: float):
    d = ImageDraw.Draw(canvas)
    x0, x1 = PAINEL[0] + 40, PAINEL[2] - 40
    y = BARRA_Y
    d.rounded_rectangle((x0, y - 2, x1, y + 2), 2, fill=(255, 255, 255, 90))
    xp = x0 + (x1 - x0) * min(1.0, t / total)
    d.rounded_rectangle((x0, y - 2, xp, y + 2), 2, fill=(255, 255, 255, 255))
    d.ellipse((xp - 11, y - 11, xp + 11, y + 11), fill=(255, 255, 255, 255))
    fs = compose._font_peso(cfg, 20, "SemiBold")
    a, b = int(t), int(total)
    d.text((x0, y + 20), f"{a // 60}:{a % 60:02d}", font=fs, fill=(220, 218, 214))
    fim = f"{b // 60}:{b % 60:02d}"
    d.text((x1 - d.textlength(fim, font=fs), y + 20), fim, font=fs, fill=(220, 218, 214))


def player(rows, cfg, dest: Path, text: str | None = None, creditos: dict | None = None,
           por_foto: float = 3.0, fade: float = 0.6) -> Path:
    """Story em vídeo: as fotos passam em slide (fusão suave e zoom lento) e a barra cresce até o fim."""
    c = creditos or {}
    cw, ch = CARTAO[2] - CARTAO[0], CARTAO[3] - CARTAO[1]
    fotos = [compose._polish(compose.smart_fit(compose._load(r), (round(cw * 1.08), round(ch * 1.08)))) for r in rows[:5]]
    total = por_foto * len(fotos)
    n = round(total * FPS)
    painel = _painel(cfg, text, c)
    dest = Path(dest)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(dest)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for k in range(n):
            t = k / FPS
            i = min(int(t // por_foto), len(fotos) - 1)
            zoom = 1.0 + 0.06 * ((t - i * por_foto) / por_foto)
            frame = _cena(fotos[i], zoom)
            resto = (i + 1) * por_foto - t
            if i + 1 < len(fotos) and resto < fade:
                prox = _cena(fotos[i + 1], 1.0)
                frame = Image.blend(frame, prox, 1 - resto / fade)
            frame.alpha_composite(painel)
            _barra(frame, cfg, t + 1 / FPS, total)
            proc.stdin.write(frame.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError("ffmpeg falhou ao montar o story em vídeo")
    return dest
