"""Prévias: a fila de posts que ainda não saíram, para ver antes da publicação, aprovar ou pedir ajuste.

- `fila(db)`: posts futuros que ainda não foram publicados (rascunho, pendente, pronto ou aprovado).
- `pagina(db, cfg)`: gera output/previas/index.html, com as fotos reduzidas, a legenda, os créditos e o status.
- `registrar_ajuste(db, texto, post_id)`: grava o pedido de ajuste. Ele vira regra: a partir daí toda legenda
  nova recebe o ajuste no prompt (ver `regras_texto`). Fica em regras/ajustes.md (texto legível, no git)
  e na tabela `ajustes` do banco (vai junto no state.enc).
"""
import base64
import html
import io
import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import library

ROOT = library.ROOT
AJUSTES_MD = ROOT / "regras" / "ajustes.md"
STATUS_FILA = ("rascunho", "pendente", "pronto", "aprovado")
PREVIEW_DIR = ROOT / "output" / "previas"


def _ensure_table(db):
    db.execute("create table if not exists ajustes(id integer primary key autoincrement, created_at text,"
               " post_id integer, texto text)")


def fila(db) -> list:
    """Posts futuros ainda não publicados, na ordem em que saem."""
    agora = datetime.now().isoformat(timespec="minutes")
    marcas = ",".join("?" * len(STATUS_FILA))
    return db.execute(f"select * from posts where status in ({marcas}) and scheduled_for>=?"
                      " order by scheduled_for, id", (*STATUS_FILA, agora)).fetchall()


def feed_na_fila(db) -> int:
    """Quantos posts de feed (foto, montagem, carrossel ou reel) já estão na fila."""
    return sum(1 for p in fila(db) if p["type"] in ("feed", "reel"))


def regras_texto(db=None) -> str:
    """Ajustes que o dono pediu, para o prompt das legendas. Vazio se não houver nenhum."""
    linhas = []
    if AJUSTES_MD.exists():
        for ln in AJUSTES_MD.read_text(encoding="utf-8").splitlines():
            if ln.startswith("- "):
                # tira a data do registro ("- 2026-11-15: texto") para não repetir o mesmo ajuste
                linhas.append(re.sub(r"^\d{4}-\d{2}-\d{2}: ", "", ln[2:].strip()))
    if db is not None:
        try:
            _ensure_table(db)
            for (t,) in db.execute("select texto from ajustes order by id"):
                if t and t not in linhas:
                    linhas.append(t)
        except Exception:
            pass
    return "\n".join(f"- {x}" for x in linhas)


def registrar_ajuste(db, texto: str, post_id=None) -> None:
    """Grava o pedido como regra para as próximas prévias e, no arquivo, como registro legível."""
    texto = " ".join(str(texto or "").split())
    if not texto:
        raise ValueError("o ajuste está vazio")
    agora = datetime.now().isoformat(timespec="seconds")
    _ensure_table(db)
    db.execute("insert into ajustes(created_at, post_id, texto) values(?,?,?)", (agora, post_id, texto))
    db.commit()
    AJUSTES_MD.parent.mkdir(parents=True, exist_ok=True)
    cabecalho = "" if AJUSTES_MD.exists() else (
        "# Ajustes pedidos nas prévias\n\nCada linha vira regra nas legendas novas (ver autopost/previas.py).\n\n")
    with AJUSTES_MD.open("a", encoding="utf-8") as f:
        f.write(cabecalho + f"- {agora[:10]}: {texto}\n")


def _miniatura(path: Path, lado: int = 480) -> str | None:
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    im.thumbnail((lado, lado))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.standard_b64encode(buf.getvalue()).decode()


def _midia_html(files) -> str:
    partes = []
    for f in files:
        f = Path(f)
        if f.suffix.lower() == ".mp4":
            partes.append('<div class="video">Vídeo (reel): a prévia em vídeo fica no arquivo do output</div>')
            continue
        uri = _miniatura(f)
        if uri:
            partes.append(f'<img src="{uri}" alt="">')
    return "".join(partes)


def pagina(db, cfg: dict) -> Path:
    """Escreve output/previas/index.html com a fila inteira, pronta para abrir no navegador."""
    itens = fila(db)
    cards = []
    for p in itens:
        meta = json.loads(p["meta"] or "{}")
        texto = p["caption"] or ""
        if p["type"] == "story":
            texto = f"Story ({meta.get('modelo', 'modelo')}): “{meta.get('texto_story', '')}”"
        try:
            files = json.loads(p["files"] or "[]")
        except Exception:
            files = []
        quando = p["scheduled_for"].replace("T", " ")
        cards.append(
            f'<article class="{html.escape(p["type"])}">'
            f'<div class="midia">{_midia_html(files)}</div>'
            f'<div class="texto"><div class="cab"><b>#{p["id"]} · {html.escape(p["type"])}</b>'
            f'<span>{html.escape(quando)}</span><em>{html.escape(p["status"])}</em></div>'
            f'<p>{html.escape(texto)}</p></div></article>')
    feed = sum(1 for p in itens if p["type"] in ("feed", "reel"))
    meta_fila = (cfg.get("previas") or {}).get("fila_minima", 10)
    ajustes = regras_texto(db)
    lista_ajustes = "".join(f"<li>{html.escape(x[2:])}</li>" for x in ajustes.splitlines()) or "<li>Nenhum ainda.</li>"
    doc = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Prévias do Instagram</title>
<style>
:root{{--fundo:#f4efe8;--texto:#222;--card:#fff;--linha:#0001}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--fundo:#161413;--texto:#eee;--card:#221f1d;--linha:#fff1}}}}
:root[data-theme="dark"]{{--fundo:#161413;--texto:#eee;--card:#221f1d;--linha:#fff1}}
body{{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.45 system-ui,sans-serif}}
header{{padding:20px 16px 8px}} h1{{margin:0 0 6px;font-size:22px}} .resumo{{opacity:.8}}
section.ajustes{{margin:12px 16px;padding:12px 14px;border-radius:12px;background:var(--card);box-shadow:0 2px 10px var(--linha)}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;padding:12px 16px 32px}}
article{{background:var(--card);border-radius:14px;overflow:hidden;box-shadow:0 2px 10px var(--linha)}}
.midia{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory}} .midia img{{width:100%;flex:0 0 100%;scroll-snap-align:start;display:block}}
.video{{padding:40px 12px;text-align:center;opacity:.7}}
.texto{{padding:10px 14px 14px}} .cab{{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;font-size:13px}}
.cab span{{opacity:.7}} .cab em{{margin-left:auto;font-style:normal;background:var(--fundo);padding:2px 8px;border-radius:9px}}
p{{white-space:pre-wrap;margin:8px 0 0}}
</style>
<header><h1>Prévias do Instagram</h1>
<div class="resumo">{len(itens)} posts na fila · {feed} de feed (mínimo {meta_fila}) · nada sai sem a sua aprovação</div></header>
<section class="ajustes"><b>Ajustes já gravados (valem para as próximas legendas)</b><ul>{lista_ajustes}</ul>
<small>Para pedir um ajuste, escreva na conversa do projeto: “ajuste #número: o que mudar”.</small></section>
<main>{''.join(cards) or '<p>Fila vazia.</p>'}</main></html>"""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = PREVIEW_DIR / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out
