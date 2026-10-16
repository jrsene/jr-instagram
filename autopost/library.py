"""Catálogo de mídia: varre as pastas-fonte, normaliza e pontua cada foto/vídeo."""
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageFilter

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC opcional
    pass

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".dng"}
VID_EXT = {".mp4", ".mov", ".m4v"}
CACHE_MAX = 1800  # cópia reduzida guardada em data/cache (vai junto no repositório)

SCHEMA = """
create table if not exists media(
  id text primary key, path text, kind text, taken_at text, added_at text,
  w int, h int, duration real, score real, cache text,
  used_count int default 0, last_used text);
create table if not exists posts(
  id integer primary key autoincrement, created_at text, scheduled_for text,
  type text, status text, media_ids text, files text, caption text,
  meta text, ig_id text, error text);
"""


ROOT = Path(__file__).resolve().parent.parent
FETCHERS = {}  # prefixo da origem (ex: "onedrive") -> função que rebaixa a mídia se o cache sumiu


def local(row, video: bool = False) -> Path:
    """Caminho local da cópia em cache (foto ou vídeo), rebaixando da nuvem se precisar."""
    p = Path(row["cache"])
    p = p if p.is_absolute() else ROOT / p
    if video:
        p = p.with_suffix(".mp4")
    if not p.exists():
        src = row["path"].split(":", 1)[0]
        if src in FETCHERS:
            FETCHERS[src](row, p, video)
        elif video and Path(row["path"]).exists():
            return Path(row["path"])
    return p


def dhash(path) -> str:
    g = Image.open(path).convert("L").resize((9, 8), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    return "".join("1" if b else "0" for b in (a[:, 1:] > a[:, :-1]).flatten())


def is_duplicate(db, h: str) -> bool:
    """Mesma foto vinda de lugares diferentes (iPhone, PC, Mac, Drive) não entra duas vezes."""
    for (o,) in db.execute("select phash from media where phash is not null"):
        if sum(x != y for x, y in zip(h, o)) <= 4:
            return True
    return False


def add_media(db, fid, path, kind, taken, w, h, dur, score, cache: Path) -> bool:
    ph = dhash(cache)
    if is_duplicate(db, ph):
        return False
    rel = cache.relative_to(ROOT) if cache.is_relative_to(ROOT) else cache
    db.execute("insert into media(id,path,kind,taken_at,w,h,duration,score,cache,added_at)"
               " values(?,?,?,?,?,?,?,?,?,?)",
               (fid, path, kind, taken, w, h, dur, score, str(rel), datetime.now().isoformat(timespec="seconds")))
    db.execute("update media set phash=? where id=?", (ph, fid))
    return True


def connect(root: Path) -> sqlite3.Connection:
    (root / "data").mkdir(exist_ok=True)
    db = sqlite3.connect(root / "data" / "library.db")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("pragma table_info(media)")}
    for col, typ in (("ok", "int"), ("motivo", "text"), ("tags", "text"), ("phash", "text")):
        if col not in cols:  # bancos antigos ganham as colunas da curadoria
            db.execute(f"alter table media add column {col} {typ}")
    return db


def _fingerprint(p: Path) -> str:
    h = hashlib.sha1()
    st = p.stat()
    h.update(f"{st.st_size}".encode())
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _open_image(p: Path) -> Image.Image:
    if p.suffix.lower() == ".dng":
        try:
            import rawpy
            with rawpy.imread(str(p)) as raw:
                return Image.fromarray(raw.postprocess(use_camera_wb=True))
        except Exception:
            pass  # alguns "DNG" são JPEG por dentro
    im = Image.open(p)
    return ImageOps.exif_transpose(im).convert("RGB")


def _taken_at(p: Path, im: Image.Image | None) -> str:
    if im is not None:
        try:
            exif = im.getexif()
            dt = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if dt:
                return datetime.strptime(dt[:19], "%Y:%m:%d %H:%M:%S").isoformat()
        except Exception:
            pass
    return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")


def quality(im: Image.Image) -> float:
    """0-1: nitidez (variância do Laplaciano) + exposição razoável."""
    g = np.asarray(im.convert("L").resize((512, int(512 * im.height / im.width))), dtype=np.float32)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    sharp = min(1.0, lap.var() / 400.0)
    mean = g.mean() / 255
    expo = 1 - min(1.0, abs(mean - 0.5) * 2) ** 2
    return round(float(0.65 * sharp + 0.35 * expo), 3)


def _probe_video(p: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(p)],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    return s["width"], s["height"], float(d["format"]["duration"])


def ingest(root: Path, cfg: dict, log=print) -> int:
    db = connect(root)
    cache_dir = root / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    known = {r["id"] for r in db.execute("select id from media")}
    added = 0
    for src in cfg.get("fontes", ["inbox"]):
        base = (root / src) if not Path(src).is_absolute() else Path(src)
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            ext = p.suffix.lower()
            if not p.is_file() or ext not in IMG_EXT | VID_EXT:
                continue
            fid = _fingerprint(p)
            if fid in known:
                continue
            try:
                if ext in IMG_EXT:
                    im = _open_image(p)
                    taken = _taken_at(p, Image.open(p) if ext not in {".dng"} else None)
                    im.thumbnail((CACHE_MAX, CACHE_MAX), Image.LANCZOS)
                    cache = cache_dir / f"{fid}.jpg"
                    im.save(cache, quality=88)
                    row = (fid, str(p), "image", taken, im.width, im.height, None, quality(im), str(cache))
                else:
                    w, h, dur = _probe_video(p)
                    cache = cache_dir / f"{fid}.jpg"
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(min(1.0, dur / 2)), "-i", str(p),
                                    "-frames:v", "1", str(cache)], check=True)
                    # cópia leve do vídeo (até 60s, 1080p) para não depender do original
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(p), "-t", "60", "-vf",
                                    "scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)'",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "aac",
                                    "-movflags", "+faststart", str(cache_dir / f"{fid}.mp4")], check=True)
                    row = (fid, str(p), "video", _taken_at(p, None), w, h, dur, 0.7, str(cache))
            except Exception as e:  # arquivo corrompido etc.
                log(f"  ! ignorado {p.name}: {e}")
                continue
            known.add(fid)
            if not add_media(db, *row[:8], Path(row[8])):
                log(f"  = {p.name}: repetida, ignorada")
                continue
            added += 1
            log(f"  + {p.name} ({row[2]}, nota {row[7]})")
    db.commit()
    return added


def pick(db, cfg: dict, n: int, kind: str = "image", group_by_day: bool = False, exclude=()) -> list[sqlite3.Row]:
    """Escolhe n mídias: nunca usadas/menos usadas primeiro, respeitando o intervalo de repetição.
    Com group_by_day, tenta pegar fotos do mesmo dia (mesmo evento) para montagens coerentes."""
    rules = cfg.get("regras", {})
    cutoff = (datetime.now() - timedelta(days=rules.get("nao_repetir_por_dias", 45))).isoformat()
    rows = [r for r in db.execute(
        "select * from media where kind=? and ok=1 and score>=? and (last_used is null or last_used<?)"
        " order by used_count asc, added_at desc, score desc",
        (kind, rules.get("qualidade_minima", 0.25), cutoff)) if r["id"] not in exclude]
    if len(rows) < n and rules.get("reciclar_quando_faltar", True):
        # acabou o conteúdo inédito: recicla o que foi usado há mais tempo
        have = {r["id"] for r in rows} | set(exclude)
        rows += [r for r in db.execute(
            "select * from media where kind=? and ok=1 and score>=? order by last_used asc, score desc",
            (kind, rules.get("qualidade_minima", 0.25))) if r["id"] not in have]
    if not rows:
        return []
    if group_by_day:
        days: dict[str, list] = {}
        for r in rows:
            days.setdefault(r["taken_at"][:10], []).append(r)
        full = [g for g in days.values() if len(g) >= n]
        if full:
            best = max(full, key=lambda g: (-min(x["used_count"] for x in g), max(x["added_at"] for x in g)))
            return sorted(best, key=lambda r: -r["score"])[:n]
    return rows[:n]


def mark_used(db, ids):
    now = datetime.now().isoformat(timespec="seconds")
    db.executemany("update media set used_count=used_count+1, last_used=? where id=?", [(now, i) for i in ids])
    db.commit()
