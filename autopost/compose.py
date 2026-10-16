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
    try:
        return ImageFont.truetype(cfg.get("visual", {}).get("fonte", ""), size)
    except Exception:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


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


def story(rows, cfg, text: str | None = None) -> Image.Image:
    """Story 9:16: fundo desfocado da própria foto + foto(s) com cantos arredondados + texto curto."""
    v = cfg.get("visual", {})
    W, H = STORY
    base = _load(rows[0])
    bg = smart_fit(base, (W // 4, H // 4)).filter(ImageFilter.GaussianBlur(14)).resize(STORY, Image.LANCZOS)
    bg = ImageEnhance.Brightness(bg).enhance(0.62)
    canvas = bg.convert("RGBA")
    r = v.get("cantos", 28)
    margin = 70
    if len(rows) == 1:
        im = base
        ratio = min((W - 2 * margin) / im.width, (H * 0.68) / im.height)
        im = _polish(im.resize((round(im.width * ratio), round(im.height * ratio)), Image.LANCZOS))
        boxes = [((W - im.width) // 2, (H - im.height) // 2 - 40, im)]
    else:
        n = len(rows)
        cell_h = (H - 2 * 200 - (n - 1) * 24) // n
        boxes = []
        for i, row in enumerate(rows):
            im = _polish(smart_fit(_load(row), (W - 2 * margin, cell_h)))
            boxes.append((margin, 200 + i * (cell_h + 24), im))
    for x, y, im in boxes:
        shadow = Image.new("RGBA", (im.width + 60, im.height + 60), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((30, 40, im.width + 30, im.height + 40), r, fill=(0, 0, 0, 110))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)), (x - 30, y - 30))
        canvas.alpha_composite(_round(im, r), (x, y))
    d = ImageDraw.Draw(canvas)
    if text:
        f = _font(cfg, 58)
        lines = _wrap(d, text, f, W - 2 * margin - 40)[:3]
        lh = 72
        y = H - 170 - lh * len(lines) if len(rows) == 1 else 70
        for ln in lines:
            tw = d.textlength(ln, font=f)
            pad = 22
            d.rounded_rectangle(((W - tw) / 2 - pad, y - 6, (W + tw) / 2 + pad, y + lh - 4), 16, fill=(255, 255, 255, 235))
            d.text(((W - tw) / 2, y), ln, font=f, fill=(20, 20, 20))
            y += lh
    handle = cfg.get("perfil", {}).get("handle")
    if handle:
        f = _font(cfg, 34)
        tw = d.textlength(handle, font=f)
        d.text(((W - tw) / 2, H - 90), handle, font=f, fill=(255, 255, 255, 200))
    return canvas.convert("RGB")


def carousel(rows, cfg, seed=None) -> list[Image.Image]:
    """Carrossel: capa em montagem + fotos individuais."""
    slides = []
    if len(rows) >= 4:
        slides.append(collage(rows[:4], cfg, seed=seed))
    slides += [single(r, cfg) for r in rows]
    return slides[:10]


def reel(rows, cfg, out: Path, music: Path | None = None, per=2.4) -> Path:
    """Reel 9:16 a partir de fotos: zoom suave (Ken Burns) com transições."""
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
        if music:
            cmd += ["-i", str(music)]
        if filt:
            cmd += ["-filter_complex", ";".join(filt), "-map", last]
        else:
            cmd += ["-map", "0:v"]
        if music:
            cmd += ["-map", f"{len(clips)}:a", "-af", f"afade=t=out:st={total - 1:.2f}:d=1", "-c:a", "aac", "-shortest"]
        cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    return out


def video_reel(row, out: Path, max_s=30) -> Path:
    """Vídeo seu → Reel 9:16 (corta no máximo max_s e preenche com fundo desfocado se for horizontal)."""
    W, H = STORY
    vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2,eq=brightness=-0.12[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    src = library.local(row, video=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", str(max_s), "-filter_complex", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-movflags", "+faststart",
                    str(out)], check=True)
    return out
