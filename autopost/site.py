"""Galeria do site (jrobras.com): fotos de obras entregues que o Junior já aprovou, com o crédito
do arquiteto e do fotógrafo de cada álbum. Lê a mesma base pública que a página /galeria usa."""
import io
import json

import requests
from PIL import Image, ImageOps

from . import library

FIRESTORE = "https://firestore.googleapis.com/v1/projects/{projeto}/databases/(default)/documents:runQuery"


def _val(f: dict, k: str) -> str:
    v = f.get(k) or {}
    return str(next(iter(v.values()), "") or "").strip()


def _docs(projeto: str) -> list[dict]:
    filtro = lambda campo: {"fieldFilter": {"field": {"fieldPath": campo}, "op": "EQUAL", "value": {"booleanValue": True}}}
    body = {"structuredQuery": {"from": [{"collectionId": "midia_jr"}],
                                "where": {"compositeFilter": {"op": "AND", "filters": [filtro("usarSite"), filtro("publicada")]}}}}
    r = requests.post(FIRESTORE.format(projeto=projeto), json=body, timeout=60)
    r.raise_for_status()
    return [d["document"] for d in r.json() if "document" in d]


def _arroba(h: str) -> str:
    h = h.strip().split("?")[0].rstrip("/").split("/")[-1].lstrip("@")
    return f"@{h}" if h else ""


def _download(url: str, dest) -> Image.Image:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    im.thumbnail((library.CACHE_MAX, library.CACHE_MAX), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, quality=92)
    return im


def _fetch(row, dest, video: bool):
    url = (json.loads(row["credito"] or "{}")).get("url")
    if url:
        _download(url, dest)


library.FETCHERS["site"] = _fetch


def sync(db, cfg: dict, log=print) -> int:
    sc = cfg.get("site", {}) or {}
    if not sc.get("ativo"):
        return 0
    docs = _docs(sc.get("firebase_projeto", "jr-zacaria"))
    fotos = [d for d in docs if _val(d["fields"], "tipo").startswith("image/")]
    # quem não tem @ preenchido num álbum herda o @ que o mesmo nome tem em outro álbum
    arroba = {}
    for d in fotos:
        f = d["fields"]
        for nome, ig in (("nomeArquiteto", "instagramArquiteto"), ("nomeFotografo", "instagramFotografo")):
            if _val(f, nome) and _val(f, ig):
                arroba[_val(f, nome).lower()] = _arroba(_val(f, ig))
    known = {r["path"] for r in db.execute("select path from media where path like 'site:%'")}
    cache_dir = library.ROOT / "data" / "cache"
    added = 0
    for d in fotos:
        f = d["fields"]
        sid = d["name"].rsplit("/", 1)[-1]
        path = f"site:{sid}"
        album = _val(f, "pastaOrigem") or _val(f, "albumOrigem") or _val(f, "obraNome") or _val(f, "titulo")
        arq = _val(f, "nomeArquiteto") or _val(f, "creditoProjeto")
        fot = _val(f, "nomeFotografo") or (_val(f, "creditoFotografo") if not _val(f, "creditoFotografo").startswith("@") else "")
        cred = {"album": album, "descricao": _val(f, "descricaoAlbum")[:500], "url": _val(f, "url"),
                "arquiteto": arq, "arquiteto_ig": _arroba(_val(f, "instagramArquiteto")) or arroba.get(arq.lower(), ""),
                "fotografo": fot,
                "fotografo_ig": _arroba(_val(f, "instagramFotografo") or (_val(f, "creditoFotografo") if _val(f, "creditoFotografo").startswith("@") else ""))
                                or arroba.get(fot.lower(), "")}
        if path in known:  # crédito pode ter sido corrigido no site
            db.execute("update media set credito=?, album=? where path=?", (json.dumps(cred, ensure_ascii=False), album, path))
            continue
        if not cred["url"]:
            continue
        fid = "site_" + sid[-24:]
        cache = cache_dir / f"{fid}.jpg"
        try:
            im = _download(cred["url"], cache)
            ph = library.dhash(cache)
            # a mesma foto pode já ter vindo do celular: a versão do site (com crédito) é a que vale
            for row in db.execute("select id, phash from media where phash is not null and path not like 'site:%'").fetchall():
                if sum(x != y for x, y in zip(ph, row["phash"])) <= 4:
                    db.execute("update media set ok=0, motivo='está na galeria do site' where id=?", (row["id"],))
            rel = cache.relative_to(library.ROOT)
            score = round(0.85 + 0.1 * library.quality(im), 3)  # aprovadas pelo dono: sempre acima da régua do feed
            db.execute("insert into media(id,path,kind,taken_at,w,h,score,cache,added_at,ok,motivo,tags,phash,album,credito)"
                       " values(?,?,'image',?,?,?,?,?,datetime('now'),1,'galeria do site',?,?,?,?)",
                       (fid, path, _val(f, "criadoEmISO")[:19], im.width, im.height, score, str(rel),
                        json.dumps([album], ensure_ascii=False), ph, album, json.dumps(cred, ensure_ascii=False)))
            added += 1
        except Exception as e:
            log(f"  ! site {album}: {type(e).__name__}: {str(e)[:120]}")
    db.commit()
    return added


def _nome_e_arroba(nome: str, ig: str) -> str:
    """Mesmo formato dos créditos do JR OS (galeria e carrossel): "Nome · @perfil"."""
    nome = (nome or "").strip()
    if ig and nome.lstrip("@").lower() == ig.lstrip("@").lower():
        nome = ""
    return " · ".join(x for x in (nome, ig) if x)


def creditos(rows) -> dict:
    """Arquitetos e fotógrafos das fotos de um post (sem repetir)."""
    arq, fot, albuns, nomes = [], [], [], []
    arq_txt, fot_txt = [], []
    for r in rows:
        c = json.loads((r["credito"] if "credito" in r.keys() else None) or "{}")
        if not c:
            continue
        for lista, txt, nome, ig in ((arq, arq_txt, c.get("arquiteto"), c.get("arquiteto_ig")),
                                     (fot, fot_txt, c.get("fotografo"), c.get("fotografo_ig"))):
            item = ig or nome
            if item and item not in lista:
                lista.append(item)
                txt.append(_nome_e_arroba(nome, ig))
        if c.get("arquiteto") and c["arquiteto"] not in nomes:
            nomes.append(c["arquiteto"])
        if c.get("album") and c["album"] not in [a["album"] for a in albuns]:
            albuns.append({"album": c["album"], "descricao": c.get("descricao", "")})
    marcar = [x.lstrip("@") for x in arq + fot if x.startswith("@")]
    return {"arquiteto": arq, "fotografo": fot, "marcar": marcar, "albuns": albuns, "nomes_arquitetos": nomes,
            "arquiteto_txt": arq_txt, "fotografo_txt": fot_txt}


def linha_creditos(c: dict) -> str:
    """Bloco de créditos da legenda, no padrão das artes da galeria do JR OS."""
    arq = c.get("arquiteto_txt") or c.get("arquiteto") or []
    fot = c.get("fotografo_txt") or c.get("fotografo") or []
    if not (arq or fot or c.get("albuns")):
        return ""
    partes = ["Execução: JR Prestadora de Serviços"]
    if arq:
        partes.append(f"Arquitetura: {' e '.join(arq)}")
    if fot:
        partes.append(f"Fotografia: {' e '.join(fot)}")
    if c.get("albuns"):
        partes.append("Álbum completo: jrobras.com/galeria")
    return "\n".join(partes)
