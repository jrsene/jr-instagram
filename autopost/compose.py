"""Gera as peças visuais: foto de feed, montagens, carrossel, stories e reels."""
import random
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from . import library
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

FEED = (1080, 1350)   # 4:5, o formato que mais ocupa a tela no feed
STORY = (1080, 1920)  # 9:16


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def smart_fit(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Recorte inteligente: procura a janela com mais 'informação' (bordas/detalhe)
    em vez de cortar sempre no centro."""
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(tw, round(im.width * scale)), max(th, round(im.height * scale))), Image.LANCZOS)
    if im.size == (tw, th):
        return im
    small = im.convert("L").resize((im.width // 8 or 1, im.height // 8 or 1))
    e = np.asarray(small.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    # leve preferência pelo centro e pelo terço superior (rostos costumam estar lá)
    yy, xx = np.mgrid[0:e.shape[0], 0:e.shape[1]]
    e *= 1.0 - 0.35 * ((xx / e.shape[1] - 0.5) ** 2 + (yy / e.shape[0] - 0.42) ** 2) * 4
    cw, ch = tw // 8, th // 8
    best, bx, by = -1, 0, 0
    integ = e.cumsum(0).cumsum(1)
    integ = np.pad(integ, ((1, 0), (1, 0)))
    for y in range(0, e.shape[0] - ch + 1, max(1, (e.shape[0] - ch) // 24 or 1)):
        for x in range(0, e.shape[1] - cw + 1, max(1, (e.shape[1] - cw) // 24 or 1)):
            s = integ[y + ch, x + cw] - integ[y, x + cw] - integ[y + ch, x] + integ[y, x]
            if s > best:
                best, bx, by = s, x, y
    x0, y0 = min(bx * 8, im.width - tw), min(by * 8, im.height - th)
    return im.crop((x0, y0, x0 + tw, y0 + th))


def _load(row) -> Image.Image:
    return Image.open(library.local(row)).convert("RGB")


def _polish(im: Image.Image) -> Image.Image:
    """Ajuste leve e consistente para o feed ter 'cara' de uma mesma série."""
    im = ImageEnhance.Contrast(im).enhance(1.06)
    im = ImageEnhance.Color(im).enhance(1.08)
    return im


def _round(im: Image.Image, r: int) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *im.size), r, fill=255)
    im = im.convert("RGBA")
    im.putalpha(mask)
    return im


# ---------- layouts de montagem (frações do canvas: x, y, w, h) ----------
LAYOUTS = {
    2: [[(0, 0, .5, 1), (.5, 0, .5, 1)],
        [(0, 0, 1, .5), (0, .5, 1, .5)]],
    3: [[(0, 0, .6, 1), (.6, 0, .4, .5), (.6, .5, .4, .5)],
        [(0, 0, 1, .58), (0, .58, .5, .42), (.5, .58, .5, .42)]],
    4: [[(0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5), (.5, .5, .5, .5)],
        [(0, 0, 1, .55), (0, .55, 1 / 3, .45), (1 / 3, .55, 1 / 3, .45), (2 / 3, .55, 1 / 3, .45)]],
    5: [[(0, 0, .5, .6), (.5, 0, .5, .6), (0, .6, 1 / 3, .4), (1 / 3, .6, 1 / 3, .4), (2 / 3, .6, 1 / 3, .4)]],
    6: [[(0, 0, 1 / 3, .5), (1 / 3, 0, 1 / 3, .5), (2 / 3, 0, 1 / 3, .5),
         (0, .5, 1 / 3, .5), (1 / 3, .5, 1 / 3, .5), (2 / 3, .5, 1 / 3, .5)]],
}


def collage(rows, cfg, size=FEED, seed=None) -> Image.Image:
    v = cfg.get("visual", {})
    gap, bg = v.get("espaco", 14), _hex(v.get("fundo", "#F4EFE8"))
    rnd = random.Random(seed)
    layout = rnd.choice(LAYOUTS[len(rows)])
    W, H = size
    canvas = Image.new("RGB", size, bg)
    # foto mais "forte" vai para a célula maior
    cells = sorted(layout, key=lambda c: -c[2] * c[3])
    imgs = sorted(rows, key=lambda r: -r["score"])
    for (fx, fy, fw, fh), r in zip(cells, imgs):
        x0, y0 = round(fx * (W - gap)) + gap, round(fy * (H - gap)) + gap
        x1, y1 = round((fx + fw) * (W - gap)), round((fy + fh) * (H - gap))
        canvas.paste(_polish(smart_fit(_load(r), (x1 - x0, y1 - y0))), (x0, y0))
    return canvas


def single(row, cfg) -> Image.Image:
    return _polish(smart_fit(_load(row), FEED))


def _font(cfg, size):
    for name in (cfg.get("visual", {}).get("fonte", ""), "DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default(size)


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


# Identidade das artes do JR OS (galeria do site e carrossel "Como a JR fez", feitas pelo Antigravity)
JR_DOURADO = (201, 162, 75)    # #C9A24B
JR_CREME = (233, 210, 160)     # #E9D2A0
JR_FUNDO = (7, 6, 10)
JR_QUADRO = (16, 13, 18)       # #100D12


def _font_peso(cfg, size, peso="Bold"):
    """Fonte do perfil no peso pedido (Inter: SemiBold, Bold, ExtraBold), com alternativas."""
    base = cfg.get("visual", {}).get("fonte", "")
    nomes = [base.replace("Bold", peso)] if "Bold" in base else []
    nomes += [base, "DejaVuSans-Bold.ttf" if peso != "SemiBold" else "DejaVuSans.ttf", "arialbd.ttf"]
    for name in nomes:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default(size)


def story(rows, cfg, text: str | None = None, credito: str = "", creditos: dict | None = None,
          selo: str | None = None) -> Image.Image:
    """Story 9:16 no visual do JR OS: foto inteira num quadro escuro (sem cortar projeto em paisagem),
    selo JR no alto, título curto e, quando a foto é da galeria do site, arquitetura, fotografia e o
    convite para ver o álbum em jrobras.com."""
    W, H = STORY
    c = creditos or {}
    do_site = bool(c.get("albuns") or c.get("arquiteto") or c.get("fotografo"))
    base = _load(rows[0])
    bg = smart_fit(base, (W // 2, H // 2)).filter(ImageFilter.GaussianBlur(6)).resize(STORY, Image.LANCZOS)
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(Image.new("RGBA", STORY, (*JR_FUNDO, 148)))

    quadro = (54, 190, W - 54, 1310)
    qw, qh = quadro[2] - quadro[0], quadro[3] - quadro[1]
    d = ImageDraw.Draw(canvas)
    if len(rows) == 1:
        # quadro do tamanho da foto (projeto em paisagem não ganha faixas pretas), centrado na área
        im = _polish(base)
        k = min(qw / im.width, qh / im.height)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        px, py = quadro[0] + (qw - im.width) // 2, quadro[1] + (qh - im.height) // 2
        d.rectangle((px - 10, py - 10, px + im.width + 10, py + im.height + 10), fill=(*JR_QUADRO, 255))
        canvas.alpha_composite(im.convert("RGBA"), (px, py))
    else:
        d.rectangle(quadro, fill=(*JR_QUADRO, 255))
        n, gap = len(rows), 14
        ch = (qh - (n - 1) * gap) // n
        for i, row in enumerate(rows):
            im = _polish(smart_fit(_load(row), (qw, ch)))
            canvas.alpha_composite(im.convert("RGBA"), (quadro[0], quadro[1] + i * (ch + gap)))

    sombra = Image.new("RGBA", (1, 256))
    for y in range(256):
        a = 0 if y < 70 else int(min(1, (y - 70) / 186) ** 1.2 * 240)
        sombra.putpixel((0, y), (*JR_FUNDO, a))
    canvas.alpha_composite(sombra.resize((W, H - int(H * 0.47))), (0, int(H * 0.47)))

    d = ImageDraw.Draw(canvas)
    rotulo = "OBRAS CONCLUÍDAS" if do_site else "PRESTADORA DE SERVIÇOS"
    fr = _font_peso(cfg, 18, "Bold")
    d.rectangle((54, 58, 146 + d.textlength(rotulo, font=fr) + 26, 130), fill=(*JR_FUNDO, 190))
    d.text((78, 70), "JR", font=_font_peso(cfg, 40, "ExtraBold"), fill=(245, 243, 247))
    d.text((146, 85), rotulo, font=fr, fill=(245, 243, 247))

    x, y, larg = 62, 1372, W - 124
    selo = selo or ("PROJETO CONCLUÍDO" if do_site else "NOSSO TRABALHO")
    d.text((x, y), selo.upper(), font=_font_peso(cfg, 27, "Bold"), fill=JR_DOURADO)
    y += 52
    if text:
        f = _font_peso(cfg, 60, "ExtraBold")
        linhas = _wrap(d, text, f, larg)
        if len(linhas) > 2:
            linhas = linhas[:2]
            while linhas[1] and d.textlength(linhas[1] + "…", font=f) > larg:
                linhas[1] = linhas[1][:-1]
            linhas[1] = linhas[1].rstrip() + "…"
        for ln in linhas:
            d.text((x, y), ln, font=f, fill=(255, 255, 255))
            y += 72
    y += 18
    f = _font_peso(cfg, 29, "SemiBold")
    arq = c.get("arquiteto_txt") or c.get("arquiteto") or []
    fot = c.get("fotografo_txt") or c.get("fotografo") or []
    for rotulo, quem, cor in (("Arquitetura", arq, JR_CREME), ("Fotografia", fot, (216, 210, 196))):
        if quem:
            linha = f"{rotulo}: {' e '.join(quem)}"
            while d.textlength(linha, font=f) > larg and len(linha) > 10:
                linha = linha[:-2].rstrip() + "…"
            d.text((x, y), linha, font=f, fill=cor)
            y += 44
    if credito and not (arq or fot):  # compatibilidade: crédito já pronto em texto
        d.text((x, y), credito, font=f, fill=JR_CREME)
    rodape = "Veja o álbum completo em jrobras.com" if do_site else cfg.get("perfil", {}).get("handle", "")
    if rodape:
        d.text((x, H - 205), rodape, font=_font_peso(cfg, 27, "SemiBold"), fill=(245, 243, 247))
    return canvas.convert("RGB")


def carousel(rows, cfg, seed=None) -> list[Image.Image]:
    """Carrossel: capa em montagem + fotos individuais."""
    slides = []
    if len(rows) >= 4:
        slides.append(collage(rows[:4], cfg, seed=seed))
    slides += [single(r, cfg) for r in rows]
    return slides[:10]


def reel(rows, cfg, out: Path, music: Path | None = None, per=2.4, voice: Path | None = None,
         falado: str = "") -> Path:
    """Reel 9:16 a partir de fotos: zoom suave (Ken Burns) com transições.
    Com voice (narração), a música abaixa enquanto a voz fala e o texto falado aparece como legenda."""
    W, H = STORY
    fps = 30
    frames = int(per * fps)
    with tempfile.TemporaryDirectory() as td:
        clips = []
        for i, r in enumerate(rows):
            src = Path(td) / f"s{i}.jpg"
            smart_fit(_polish(_load(r)), (int(W * 1.25), int(H * 1.25))).save(src, quality=92)
            zin = i % 2 == 0
            z = f"'min(1+0.0018*on,1.2)'" if zin else f"'max(1.2-0.0018*on,1)'"
            clip = Path(td) / f"c{i}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(src), "-t", str(per),
                "-vf", f"zoompan=z={z}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={fps},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(clip)], check=True)
            clips.append(clip)
        # junta com transição de 0.4s
        xf = 0.4
        inputs, filt, last, offset = [], [], "[0:v]", 0.0
        for c in clips:
            inputs += ["-i", str(c)]
        for i in range(1, len(clips)):
            offset += per - xf
            tag = f"[v{i}]"
            filt.append(f"{last}[{i}:v]xfade=transition=fade:duration={xf}:offset={offset:.2f}{tag}")
            last = tag
        total = per * len(clips) - xf * (len(clips) - 1)
        cmd = ["ffmpeg", "-y", "-v", "error", *inputs]
        n = len(clips)
        if music:
            cmd += ["-i", str(music)]
        if voice:
            cmd += ["-i", str(voice)]
        fade = f"afade=t=out:st={total - 1:.2f}:d=1"
        audio = None
        if music and voice:
            # voz entra 0,5 s depois; música fica baixinha por baixo
            filt.append(f"[{n}:a]volume=0.22,atrim=0:{total:.2f}[m];[{n + 1}:a]adelay=500|500,volume=1.6[vo];"
                        f"[m][vo]amix=inputs=2:duration=first:normalize=0,{fade}[a]")
            audio = "[a]"
        elif voice:
            filt.append(f"[{n}:a]adelay=500|500,apad,atrim=0:{total:.2f},{fade}[a]")
            audio = "[a]"
        if voice and falado and cfg.get("edicao", {}).get("legenda_fala", True):
            from . import edicao
            ass = edicao.legenda_ass(edicao.palavras_no_tempo(falado, 0.5, edicao.duracao(voice)),
                                     Path(td) / "fala.ass", (W, H))
            filt.append(f"{last}subtitles='{ass}'[vs]")
            last = "[vs]"
        if filt:
            cmd += ["-filter_complex", ";".join(filt), "-map", last]
        else:
            cmd += ["-map", "0:v"]
        if audio:
            cmd += ["-map", audio, "-c:a", "aac"]
        elif music:
            cmd += ["-map", f"{n}:a", "-af", fade, "-c:a", "aac", "-shortest"]
        cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    return out


def video_reel(row, out: Path, max_s=30, cfg=None, log=print) -> Path:
    """Vídeo seu → Reel 9:16 (corta no máximo max_s e preenche com fundo desfocado se for horizontal).
    Se tiver fala, corta as pausas e coloca legenda no tempo de cada palavra."""
    W, H = STORY
    vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,eq=brightness=-0.12[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    src = library.local(row, video=True)
    ec = (cfg or {}).get("edicao", {})
    if cfg is not None and ec.get("cortar_pausas", True):
        from . import edicao
        words = [w for w in edicao.transcrever(src, cfg, log=log) if w[0] < max_s]
        if len(words) >= 4:
            trechos = edicao.trechos_com_fala(words, min(max_s, edicao.duracao(src)), pausa=ec.get("pausa_max", 0.6))
            novo = edicao.remapear(words, trechos)
            with tempfile.TemporaryDirectory() as td:
                vf2 = vf
                if ec.get("legenda_fala", True):
                    ass = edicao.legenda_ass(novo, Path(td) / "fala.ass", (W, H))
                    vf2 = vf.replace(",format=yuv420p", f",subtitles='{ass}',format=yuv420p")
                edicao.cortar(src, out, trechos, vf2)
            log(f"  edição: {len(trechos)} trecho(s) com fala, {len(words)} palavras legendadas")
            return out
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", str(max_s), "-filter_complex", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-movflags", "+faststart",
                    str(out)], check=True)
    return out
