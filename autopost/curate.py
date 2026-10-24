"""Filtro com IA: decide o que serve para o Instagram (tira prints, documentos, fotos privadas, repetidas)."""
import json
import os
import re

from pydantic import BaseModel

from . import library
from .captions import _b64


class Verdict(BaseModel):
    indice: int
    postavel: bool
    motivo: str          # curto, em português
    tags: list[str]      # ex: ["praia", "pôr do sol", "amigos"]
    nota_estetica: float # 0 a 1


class Batch(BaseModel):
    fotos: list[Verdict]


SCREEN = re.compile(r"(screenshot|captura|screen ?shot|whatsapp image|print)", re.I)


def _heuristic(row) -> tuple[int, str]:
    name = os.path.basename(row["path"])
    if SCREEN.search(name):
        return 0, "parece print de tela"
    if name.lower().endswith(".png") and row["h"] and row["w"] and row["h"] / row["w"] > 1.9:
        return 0, "parece print de celular"
    return 1, "aprovada sem IA"


def _tipo(cfg) -> str:
    p = cfg.get("perfil", {})
    return f"da empresa {p.get('nome', '')}".strip() if p.get("tipo") == "empresa" else "pessoal"


def curate(db, cfg, log=print, batch=8) -> int:
    rows = db.execute("select * from media where ok is null").fetchall()
    if not rows:
        return 0
    crit = cfg.get("curadoria", {})
    use_ai = crit.get("ia", True) and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    client = None
    if use_ai:
        import anthropic
        client = anthropic.Anthropic()
    for i in range(0, len(rows), batch):
        chunk, imgs = [], []
        for r in rows[i:i + batch]:  # foto sem cópia local (nem na nuvem) sai da fila em vez de derrubar a rodada
            try:
                imgs.append(_b64(library.local(r), 512))
                chunk.append(r)
            except Exception as e:
                db.execute("update media set ok=0, motivo=? where id=?", (f"arquivo indisponível ({type(e).__name__})", r["id"]))
        verdicts = {}
        if client and chunk:
            content = []
            for k, img in enumerate(imgs):
                content += [{"type": "text", "text": f"Foto {k}:"},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}}]
            content.append({"type": "text", "text": (
                f"Você faz a curadoria do Instagram {_tipo(cfg)} {cfg.get('perfil', {}).get('handle', '')}. "
                "Para cada foto, diga se é boa para postar. Reprove: prints de tela, documentos, notas fiscais, "
                "fotos acidentais, muito borradas ou escuras, fotos íntimas ou que exponham dados pessoais, "
                "e imagens que claramente não são do dono (memes, imagens baixadas). "
                f"Critérios extras do dono: {crit.get('extra', 'nenhum')}. "
                "Dê também tags curtas do que aparece e uma nota estética de 0 a 1.")})
            try:
                resp = client.messages.parse(model=cfg.get("ia", {}).get("modelo", "claude-opus-5-5"),
                                             max_tokens=4000, output_config={"effort": "low"},
                                             messages=[{"role": "user", "content": content}], output_format=Batch)
                if resp.stop_reason != "refusal" and resp.parsed_output:
                    verdicts = {v.indice: v for v in resp.parsed_output.fotos}
            except Exception as e:
                log(f"  ! curadoria IA falhou ({type(e).__name__}); usando regras simples")
        for k, r in enumerate(chunk):
            v = verdicts.get(k)
            if v:
                score = round(0.5 * r["score"] + 0.5 * max(0.0, min(1.0, v.nota_estetica)), 3)
                db.execute("update media set ok=?, motivo=?, tags=?, score=? where id=?",
                           (int(v.postavel), v.motivo, json.dumps(v.tags, ensure_ascii=False), score, r["id"]))
                log(f"  {'✓' if v.postavel else '✗'} {os.path.basename(r['path'])}: {v.motivo}")
            else:
                ok, why = _heuristic(r)
                db.execute("update media set ok=?, motivo=? where id=?", (ok, why, r["id"]))
        db.commit()
    return len(rows)
