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
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import captions, compose, curate, drive, library, onedrive, site, voz

ROOT = Path(__file__).resolve().parent.parent
DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def load_cfg():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    # Decisão do dono (2026-10-24): fica em teste até a chave da Anthropic chegar, depois liga sozinho.
    if cfg.get("mode") == "dry_run" and cfg.get("ligar_com_chave") and os.environ.get("ANTHROPIC_API_KEY"):
        cfg["mode"] = cfg["ligar_com_chave"]
    return cfg


def _status(cfg):
    return {"dry_run": "rascunho", "approve": "pendente", "auto": "pronto"}[cfg.get("mode", "dry_run")]


def _save_post(db, cfg, when, ptype, rows, files, copy):
    copy = {**copy, "creditos": site.creditos(rows)}  # arquiteto e fotógrafo vão na legenda e marcados no post
    db.execute("insert into posts(created_at,scheduled_for,type,status,media_ids,files,caption,meta)"
               " values(?,?,?,?,?,?,?,?)",
               (datetime.now().isoformat(timespec="seconds"), when, ptype, _status(cfg),
                json.dumps([r["id"] for r in rows]), json.dumps([str(f) for f in files]),
                captions.full_caption(copy) if ptype != "story" else "", json.dumps(copy, ensure_ascii=False)))
    library.mark_used(db, [r["id"] for r in rows])


def plan_day(db, cfg, day: date, log=print):
    # fora do modo teste, rascunho antigo não conta: o dia é montado de novo para publicar de verdade
    teste = "" if cfg.get("mode") == "dry_run" else " and status!='rascunho'"
    if db.execute("select 1 from posts where substr(scheduled_for,1,10)=?" + teste, (day.isoformat(),)).fetchone():
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
            rows, files, copy = [], [], None
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
                    files = [compose.video_reel(vids[0], out / "reel.mp4", cfg=cfg, log=log)]
                else:
                    rows = library.pick(db, cfg, 6, group_by_day=True)
                    if len(rows) >= 3:
                        music = sorted((ROOT / cfg.get("visual", {}).get("musica_pasta", "assets/music")).glob("*.mp3"))
                        mus = music[seed % len(music)] if music else None
                        copy = captions.write(rows, cfg, kind, log=log)
                        vo = voz.falar(copy.get("narracao", ""), cfg, out / "narracao.wav", log=log)
                        files = [compose.reel(rows, cfg, out / "reel.mp4", music=mus, voice=vo,
                                              falado=copy.get("narracao", "") if vo else "")]
                        if vo:
                            log(f"  narração: “{copy['narracao']}”")
            if files:
                copy = copy or captions.write(rows, cfg, kind, log=log)
                _save_post(db, cfg, when, "reel" if kind == "reel" else "feed", rows, files, copy)
                used |= {r["id"] for r in rows}
                log(f"  feed/{kind}: {len(rows)} mídia(s) → {copy['legenda'][:60]}")
            else:
                log(f"  feed/{kind}: mídia insuficiente, pulando")
        except Exception as e:  # um post com problema não derruba o resto do dia
            log(f"  ! feed/{kind} falhou: {type(e).__name__}: {e}")

    ex = cfg.get("extras", {}) or {}
    if ex.get("resumo_semana") == DIAS[day.weekday()] and not kind:
        rows = week_media(db, day, nota=cfg.get("regras", {}).get("nota_feed", 0.75))
        if len(rows) >= 4:
            music = sorted((ROOT / cfg.get("visual", {}).get("musica_pasta", "assets/music")).glob("*.mp3"))
            copy = captions.write(rows, cfg, "resumo da semana (reel com os melhores momentos dos últimos 7 dias)", log=log)
            vo = voz.falar(copy.get("narracao", ""), cfg, out / "narracao_resumo.wav", log=log)
            files = [compose.reel(rows, cfg, out / "resumo_semana.mp4",
                                  music=music[seed % len(music)] if music else None, voice=vo,
                                  falado=copy.get("narracao", "") if vo else "")]
            _save_post(db, cfg, f"{day}T{hr.get('feed', '18:30')}", "reel", rows, files, copy)
            log(f"  resumo da semana: {len(rows)} fotos")

    times = hr.get("stories", ["09:00", "13:00", "20:00"])
    if ex.get("lembranca") == DIAS[day.weekday()]:
        rows = memories(db, day, exclude=used)
        if rows:
            anos = day.year - int(rows[0]["taken_at"][:4])
            f = out / "story_lembranca.jpg"
            compose.story(rows, cfg, text=f"Há {anos} ano{'s' if anos > 1 else ''}…", selo="Lembrança").save(f, quality=92)
            _save_post(db, cfg, f"{day}T{times[-1]}", "story", rows, [f], {"texto_story": f"Há {anos} anos", "legenda": "", "hashtags": [], "alt_text": ""})
            used |= {r["id"] for r in rows}
            log(f"  lembrança: foto de {rows[0]['taken_at'][:10]}")

    for i in range(ag.get("stories", 0) or 0):
        n = 1 if (seed + i) % 3 else 2
        rows = library.pick(db, cfg, n, group_by_day=n > 1, exclude=used, nota="nota_stories")
        if not rows:
            log("  story: sem mídia nova, pulando")
            break
        copy = captions.write(rows, cfg, "story", log=log)
        f = out / f"story_{i + 1}.jpg"
        compose.story(rows, cfg, text=copy["texto_story"], creditos=site.creditos(rows)).save(f, quality=92)
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


def week_media(db, day: date, n=8, nota=0.75) -> list:
    """As melhores fotos usadas nos posts dos últimos 7 dias, para o resumo da semana."""
    ids: list = []
    for (m,) in db.execute("select media_ids from posts where scheduled_for>=? and scheduled_for<? and type!='reel'"
                           " and status in ('publicado','pronto','aprovado')",
                           ((day - timedelta(days=7)).isoformat(), day.isoformat())):
        ids += [i for i in json.loads(m) if i not in ids]
    if not ids:
        return []
    rows = db.execute(f"select * from media where kind='image' and ok=1 and score>=? and id in ({','.join('?' * len(ids))})",
                      [nota] + ids).fetchall()
    return sorted(rows, key=lambda r: r["taken_at"] or "")[:n] if len(rows) <= n else \
        sorted(sorted(rows, key=lambda r: -r["score"])[:n], key=lambda r: r["taken_at"] or "")


def publish_due(db, cfg, log=print):
    if cfg.get("mode") == "dry_run":
        log("modo dry_run: nada é publicado")
        if os.environ.get("IG_ACCESS_TOKEN"):  # só confere se o token responde e é a conta certa
            try:
                from .publisher import Publisher
                c = Publisher(cfg, ROOT).conta()
                ok = str(c.get("user_id")) == os.environ.get("IG_USER_ID")
                log(f"instagram: @{c.get('username')} ({c.get('account_type')}, {c.get('media_count')} posts)"
                    f" · id {'confere' if ok else 'NÃO confere com IG_USER_ID'}")
            except Exception as e:
                log(f"instagram: token com problema: {str(e)[:300]}")
        return
    from .publisher import Publisher
    pub = Publisher(cfg, ROOT)
    now = datetime.now().isoformat(timespec="minutes")
    # post que perdeu o horário por mais de 3h não sai atrasado (ex.: piloto ficou parado)
    limite = (datetime.now() - timedelta(hours=3)).isoformat(timespec="minutes")
    n = db.execute("update posts set status='atrasado' where status in ('pronto','aprovado') and scheduled_for<?",
                   (limite,)).rowcount
    if n:
        log(f"  {n} post(s) passaram do horário e não serão publicados")
    # rede de segurança: post montado antes do filtro novo (ou com foto que caiu na curadoria) não sai
    regras = cfg.get("regras", {})
    for p in db.execute("select id, type, media_ids from posts where status in ('pronto','aprovado')").fetchall():
        nota = regras.get("nota_stories", 0.6) if p["type"] == "story" else regras.get("nota_feed", 0.75)
        ids = json.loads(p["media_ids"] or "[]")
        boas = db.execute(f"select count(*) from media where (ok=1 and score>=? or kind='video') and id in ({','.join('?' * len(ids))})",
                          [nota] + ids).fetchone()[0] if ids else 0
        if boas < len(ids):
            db.execute("update posts set status='descartado', error='foto abaixo da régua de qualidade' where id=?", (p["id"],))
            log(f"  post #{p['id']} ({p['type']}) descartado: tem foto abaixo da régua")
    db.commit()
    for p in db.execute("select * from posts where status in ('pronto','aprovado') and scheduled_for<=? "
                        "order by scheduled_for", (now,)).fetchall():
        try:
            meta = json.loads(p["meta"] or "{}")
            igid = pub.publish(p["type"], [Path(f) for f in json.loads(p["files"])], p["caption"], meta.get("alt_text", ""),
                               marcar=(meta.get("creditos") or {}).get("marcar", []))
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


def refazer_perfil(db, cfg):
    """Quando perfil.versao sobe, refaz a curadoria (com IA) e os posts ainda não publicados."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return
    marca = ROOT / "data" / f".perfil_v{cfg.get('perfil', {}).get('versao', 1)}"
    if marca.exists():
        return
    n = db.execute("update media set ok=null where ok is not null and kind='image' and path not like 'site:%'").rowcount
    p = db.execute("delete from posts where status in ('rascunho','pendente','pronto','aprovado') "
                   "and substr(scheduled_for,1,10)>=?", (date.today().isoformat(),)).rowcount
    db.commit()
    marca.parent.mkdir(exist_ok=True)
    marca.touch()
    print(f"perfil mudou: {n} foto(s) voltam para a curadoria e {p} post(s) futuro(s) serão refeitos")


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
    # a rodada é de hora em hora; buscar e avaliar fotos novas (que custa IA) só a cada `ingestao_horas`
    marca = ROOT / "data" / ".ultima_ingestao"
    ingerir = a.cmd == "ingest" or not marca.exists() or \
        (datetime.now().timestamp() - marca.stat().st_mtime) / 3600 >= cfg.get("ingestao_horas", 6)
    if a.cmd == "run" and not ingerir:
        print("fotos novas: já buscadas há pouco, só publicando o que venceu")
    if a.cmd in ("run", "ingest") and ingerir:
        marca.parent.mkdir(exist_ok=True)
        marca.touch()
        refazer_perfil(db, cfg)
        for nome, fn in (("lendo a galeria do site", lambda: f"{site.sync(db, cfg)} nova(s)"),
                         ("lendo o OneDrive", lambda: f"{onedrive.sync(db, cfg)} nova(s)"),
                         ("baixando do Drive", lambda: f"{drive.sync(ROOT, cfg)} arquivo(s)")):
            try:
                print(f"{nome}… {fn()}")
            except Exception as e:  # uma fonte fora do ar não impede o resto
                print(f"{nome}… falhou: {type(e).__name__}: {str(e)[:200]}")
        print(f"catalogando… {library.ingest(ROOT, cfg)} nova(s)")
        try:  # falha na curadoria não pode impedir a publicação do dia
            print(f"curadoria… {curate.curate(db, cfg)} avaliada(s)")
        except Exception as e:
            print(f"curadoria… falhou: {type(e).__name__}: {str(e)[:200]}")
        r = cfg.get("regras", {})
        q = lambda m: db.execute("select count(*) from media where kind='image' and ok=1 and score>=?", (m,)).fetchone()[0]
        print(f"fotos boas: {q(r.get('nota_feed', 0.75))} para o feed, {q(r.get('nota_stories', 0.6))} para stories")
    if a.cmd in ("run", "plan") and cfg.get("mode") != "dry_run":
        # rascunhos do modo teste que ainda não venceram são refeitos (agora com legenda da IA e status certo)
        n = db.execute("delete from posts where status='rascunho' and scheduled_for>?",
                       (datetime.now().isoformat(timespec="minutes"),)).rowcount
        db.commit()
        if n:
            print(f"{n} rascunho(s) do modo teste refeito(s) para publicar")
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
