"""Piloto automático do Instagram.

Uso:
  python -m autopost run              # rotina completa: cataloga, monta o dia, publica o que venceu, gera prévia
  python -m autopost ingest           # baixa do Drive, cataloga e faz a curadoria das novas
  python -m autopost plan [--dias 7] [--data 2026-10-20]   # gera os posts dos próximos dias
  python -m autopost publish          # publica o que está pronto e com horário vencido
  python -m autopost approve <id|all> # (modo approve) libera posts para publicação
  python -m autopost preview          # gera output/preview.html
  python -m autopost onedrive-login   # conecta o OneDrive (uma vez só)
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import captions, compose, curate, drive, library, onedrive

ROOT = Path(__file__).resolve().parent.parent
DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def load_cfg():
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def _status(cfg):
    return {"dry_run": "rascunho", "approve": "pendente", "auto": "pronto"}[cfg.get("mode", "dry_run")]


def _save_post(db, cfg, when, ptype, rows, files, copy):
    db.execute("insert into posts(created_at,scheduled_for,type,status,media_ids,files,caption,meta)"
               " values(?,?,?,?,?,?,?,?)",
               (datetime.now().isoformat(timespec="seconds"), when, ptype, _status(cfg),
                json.dumps([r["id"] for r in rows]), json.dumps([str(f) for f in files]),
                captions.full_caption(copy) if ptype != "story" else "", json.dumps(copy, ensure_ascii=False)))
    library.mark_used(db, [r["id"] for r in rows])


def plan_day(db, cfg, day: date, log=print):
    if db.execute("select 1 from posts where substr(scheduled_for,1,10)=?", (day.isoformat(),)).fetchone():
        log(f"{day}: já planejado")
        return
    ag = cfg.get("agenda", {}).get(DIAS[day.weekday()], {}) or {}
    hr = cfg.get("horarios", {})
    out = ROOT / "output" / day.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    seed = day.toordinal()
    used: set = set()
    log(f"{day} ({DIAS[day.weekday()]}):")

    kind = ag.get("feed")
    if kind:
        try:
            when = f"{day}T{hr.get('feed', '18:30')}"
            rows, files = [], []
            if kind == "foto":
                rows = library.pick(db, cfg, 1)
                if rows:
                    files = [out / "feed.jpg"]
                    compose.single(rows[0], cfg).save(files[0], quality=93)
            elif kind == "montagem":
                n = [3, 4, 2][seed % 3]
                rows = library.pick(db, cfg, n, group_by_day=True)
                if len(rows) >= 2:
                    files = [out / "feed_montagem.jpg"]
                    compose.collage(rows, cfg, seed=seed).save(files[0], quality=93)
            elif kind == "carrossel":
                rows = library.pick(db, cfg, 6, group_by_day=True)
                if len(rows) >= 2:
                    for i, im in enumerate(compose.carousel(rows, cfg, seed=seed)):
                        f = out / f"carrossel_{i + 1:02d}.jpg"
                        im.save(f, quality=93)
                        files.append(f)
            elif kind == "reel":
                vids = library.pick(db, cfg, 1, kind="video")
                if vids:
                    rows = vids
                    files = [compose.video_reel(vids[0], out / "reel.mp4")]
                else:
                    rows = library.pick(db, cfg, 6, group_by_day=True)
                    if len(rows) >= 3:
                        music = sorted((ROOT / cfg.get("visual", {}).get("musica_pasta", "assets/music")).glob("*.mp3"))
                        mus = music[seed % len(music)] if music else None
                        files = [compose.reel(rows, cfg, out / "reel.mp4", music=mus)]
            if files:
                copy = captions.write(rows, cfg, kind, log=log)
                _save_post(db, cfg, when, "reel" if kind == "reel" else "feed", rows, files, copy)
                used |= {r["id"] for r in rows}
                log(f"  feed/{kind}: {len(rows)} mídia(s) → {copy['legenda'][:60]}")
            else:
                log(f"  feed/{kind}: mídia insuficiente, pulando")
        except Exception as e:  # um post com problema não derruba o resto do dia
            log(f"  ! feed/{kind} falhou: {type(e).__name__}: {e}")

    ex = cfg.get("extras", {}) or {}
    if ex.get("resumo_semana") == DIAS[day.weekday()] and not kind:
        rows = week_media(db, day)
        if len(rows) >= 4:
            music = sorted((ROOT / cfg.get("visual", {}).get("musica_pasta", "assets/music")).glob("*.mp3"))
            files = [compose.reel(rows, cfg, out / "resumo_semana.mp4", music=music[seed % len(music)] if music else None)]
            copy = captions.write(rows, cfg, "resumo da semana (reel com os melhores momentos dos últimos 7 dias)", log=log)
            _save_post(db, cfg, f"{day}T{hr.get('feed', '18:30')}", "reel", rows, files, copy)
            log(f"  resumo da semana: {len(rows)} fotos")

    times = hr.get("stories", ["09:00", "13:00", "20:00"])
    if ex.get("lembranca") == DIAS[day.weekday()]:
        rows = memories(db, day, exclude=used)
        if rows:
            anos = day.year - int(rows[0]["taken_at"][:4])
            f = out / "story_lembranca.jpg"
            compose.story(rows, cfg, text=f"Há {anos} ano{'s' if anos > 1 else ''}…").save(f, quality=92)
            _save_post(db, cfg, f"{day}T{times[-1]}", "story", rows, [f], {"texto_story": f"Há {anos} anos", "legenda": "", "hashtags": [], "alt_text": ""})
            used |= {r["id"] for r in rows}
            log(f"  lembrança: foto de {rows[0]['taken_at'][:10]}")

    for i in range(ag.get("stories", 0) or 0):
        n = 1 if (seed + i) % 3 else 2
        rows = library.pick(db, cfg, n, group_by_day=n > 1, exclude=used)
        if not rows:
            log("  story: sem mídia nova, pulando")
            break
        copy = captions.write(rows, cfg, "story", log=log)
        f = out / f"story_{i + 1}.jpg"
        compose.story(rows, cfg, text=copy["texto_story"]).save(f, quality=92)
        _save_post(db, cfg, f"{day}T{times[i % len(times)]}", "story", rows, [f], copy)
        used |= {r["id"] for r in rows}
        log(f"  story {i + 1}: “{copy['texto_story']}”")
    db.commit()


def memories(db, day: date, exclude=(), janela=3) -> list:
    """Fotos tiradas nesta mesma época (±janela dias) em anos anteriores: a melhor delas."""
    md = {(day + timedelta(days=d)).strftime("%m-%d") for d in range(-janela, janela + 1)}
    rows = [r for r in db.execute("select * from media where kind='image' and ok=1 and taken_at<? "
                                  "order by score desc", (f"{day.year}-01-01",))
            if r["taken_at"][5:10] in md and r["id"] not in exclude]
    return rows[:1]


def week_media(db, day: date, n=8) -> list:
    """As melhores fotos usadas nos posts dos últimos 7 dias, para o resumo da semana."""
    ids: list = []
    for (m,) in db.execute("select media_ids from posts where scheduled_for>=? and scheduled_for<? and type!='reel'",
                           ((day - timedelta(days=7)).isoformat(), day.isoformat())):
        ids += [i for i in json.loads(m) if i not in ids]
    if not ids:
        return []
    rows = db.execute(f"select * from media where kind='image' and id in ({','.join('?' * len(ids))})", ids).fetchall()
    return sorted(rows, key=lambda r: r["taken_at"])[:n] if len(rows) <= n else \
        sorted(sorted(rows, key=lambda r: -r["score"])[:n], key=lambda r: r["taken_at"])


def publish_due(db, cfg, log=print):
    if cfg.get("mode") == "dry_run":
        log("modo dry_run: nada é publicado")
        return
    from .publisher import Publisher
    pub = Publisher(cfg, ROOT)
    now = datetime.now().isoformat(timespec="minutes")
    for p in db.execute("select * from posts where status in ('pronto','aprovado') and scheduled_for<=? "
                        "order by scheduled_for", (now,)).fetchall():
        try:
            meta = json.loads(p["meta"] or "{}")
            igid = pub.publish(p["type"], [Path(f) for f in json.loads(p["files"])], p["caption"], meta.get("alt_text", ""))
            db.execute("update posts set status='publicado', ig_id=? where id=?", (igid, p["id"]))
            log(f"  ✓ publicado #{p['id']} ({p['type']}) → {igid}")
        except Exception as e:
            db.execute("update posts set status='erro', error=? where id=?", (str(e)[:500], p["id"]))
            log(f"  ✗ #{p['id']}: {e}")
        db.commit()


def preview(db):
    rows = db.execute("select * from posts order by scheduled_for").fetchall()
    out = ROOT / "output"
    cards = []
    for p in rows:
        files = [Path(f) for f in json.loads(p["files"])]
        media = "".join(
            f'<video src="{f.relative_to(out).as_posix()}" controls muted loop playsinline></video>' if f.suffix == ".mp4"
            else f'<img src="{f.relative_to(out).as_posix()}" loading="lazy">' for f in files)
        meta = json.loads(p["meta"] or "{}")
        text = p["caption"] or meta.get("texto_story", "")
        cards.append(f'<article class="{p["type"]}"><div class="m">{media}</div><div class="t">'
                     f'<b>#{p["id"]} · {p["type"]} · {p["scheduled_for"].replace("T", " ")}</b>'
                     f'<span class="s">{p["status"]}</span><p>{text}</p></div></article>')
    html = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prévia do Instagram</title><style>
body{{font:15px/1.45 system-ui,sans-serif;margin:0;background:#f4efe8;color:#222}}
h1{{padding:20px 16px 0;margin:0}} main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;padding:16px}}
article{{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px #0001}}
.m{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory}} .m>*{{width:100%;flex:0 0 100%;scroll-snap-align:start;display:block}}
.t{{padding:10px 14px}} .s{{float:right;font-size:12px;background:#eee;padding:2px 8px;border-radius:9px}}
p{{white-space:pre-wrap;margin:6px 0 0}}</style>
<h1>Prévia · {len(rows)} posts</h1><main>{''.join(cards)}</main>"""
    (out / "preview.html").write_text(html)
    return out / "preview.html"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autopost")
    ap.add_argument("cmd", choices=["run", "ingest", "plan", "publish", "approve", "preview", "onedrive-login"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--dias", type=int, default=1)
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    if a.cmd == "onedrive-login":
        return onedrive.login()
    cfg = load_cfg()
    db = library.connect(ROOT)
    if a.cmd in ("run", "ingest"):
        for nome, fn in (("lendo o OneDrive", lambda: f"{onedrive.sync(db, cfg)} nova(s)"),
                         ("baixando do Drive", lambda: f"{drive.sync(ROOT, cfg)} arquivo(s)")):
            try:
                print(f"{nome}… {fn()}")
            except Exception as e:  # uma fonte fora do ar não impede o resto
                print(f"{nome}… falhou: {type(e).__name__}: {str(e)[:200]}")
        print(f"catalogando… {library.ingest(ROOT, cfg)} nova(s)")
        print(f"curadoria… {curate.curate(db, cfg)} avaliada(s)")
    if a.cmd in ("run", "plan"):
        start = date.fromisoformat(a.data) if a.data else date.today()
        for i in range(a.dias):
            plan_day(db, cfg, start + timedelta(days=i))
    if a.cmd == "approve":
        q = "update posts set status='aprovado' where status='pendente'" + ("" if a.arg == "all" else " and id=?")
        db.execute(q, () if a.arg == "all" else (int(a.arg),))
        db.commit()
    if a.cmd in ("run", "publish"):
        publish_due(db, cfg)
    if a.cmd in ("run", "plan", "preview"):
        print("prévia:", preview(db))


if __name__ == "__main__":
    sys.exit(main())
