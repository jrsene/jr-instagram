"""Legendas com IA (Claude olha as fotos e escreve no tom do perfil). Sem chave, usa modelos prontos."""
import base64
import io
import os
import random

from PIL import Image
from pydantic import BaseModel

from . import library


class Copy(BaseModel):
    legenda: str          # legenda do post (sem hashtags)
    hashtags: list[str]   # hashtags relevantes, com '#'
    texto_story: str      # frase curta (até ~8 palavras) para colocar em cima do story
    alt_text: str         # descrição acessível da imagem
    narracao: str = ""    # só para reels: 1 a 2 frases faladas em primeira pessoa (narração com a voz dele)


# Quando a IA não responde, a legenda sai sóbria e factual, com o nome do projeto (nunca frase genérica).
FALLBACK_TMPL = [
    "{album}.",
    "{album}, {cidade}.",
    "Acabamento de {album}.",
]
FALLBACK_STORY_TMPL = ["{album}", "Projeto {album}"]


def _b64(path, size=768) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _nome_projeto(rows) -> str:
    """Nome do projeto para a legenda de reserva (galeria do site); vazio se não houver."""
    from .site import creditos
    try:
        albuns = creditos(rows).get("albuns") or []
    except Exception:
        albuns = []
    return (albuns[0].get("album") or "").strip() if albuns else ""


def _contexto(rows) -> str:
    """Nome e descrição do projeto (galeria do site), para a legenda falar da obra certa."""
    from .site import creditos
    c = creditos(rows)
    if not c["albuns"]:
        return ""
    txt = "; ".join(f"{a['album']}: {a['descricao']}".strip(": ") for a in c["albuns"])
    quem = " e ".join(c["nomes_arquitetos"])
    return (f"Projeto: {txt}. " + (f"Projeto de arquitetura de {quem}. " if quem else "") +
            "Pode citar o nome do projeto e agradecer a parceria com a arquitetura; os créditos com @ já entram "
            "sozinhos no fim da legenda, então não escreva @ nem repita os créditos.\n")


def write(rows, cfg, formato: str, log=print) -> dict:
    perfil = cfg.get("perfil", {})
    fixed = perfil.get("hashtags_fixas", [])
    maxh = perfil.get("max_hashtags", 8)
    ia = cfg.get("ia", {})
    if ia.get("legendas", True) and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        try:
            import anthropic
            client = anthropic.Anthropic()
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": _b64(library.local(r))}} for r in rows[:6]]
            content.append({"type": "text", "text": (
                f"Você cuida do Instagram {perfil.get('handle', '')}. Idioma: {perfil.get('idioma', 'pt-BR')}.\n"
                f"Tom de voz: {perfil.get('voz', '')}\n"
                f"Formato do post: {formato}. As imagens acima vão juntas nesse post.\n"
                + _contexto(rows) +
                "Escreva a legenda como um profissional de arquitetura escreveria: blocos curtos, frase-tese simples, "
                "depois o que foi feito, com material, luz ou uso do espaço. Nada de adjetivo vazio, emoji, pergunta "
                "para engajar, frase de efeito, 'não é X, é Y' ou travessão. "
                "Até 3 hashtags, só de cidade ou tipo de obra. "
                "Um texto curto para o story (o nome do projeto ou a cidade, sem slogan) e um alt text descritivo. "
                + ("Como é um reel, escreva também a narração: 1 ou 2 frases curtas, faladas em primeira pessoa, "
                   "naturais como alguém contando o momento para um amigo (até ~12 segundos de fala). "
                   if "reel" in formato else "") +
                "Não invente nomes de lugares ou pessoas que não dá para ver nas fotos, "
                "e não cite dia da semana nem data.")})
            resp = client.messages.parse(
                model=ia.get("modelo", "claude-opus-5-5"),
                max_tokens=2000,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
                output_format=Copy,
            )
            if resp.stop_reason != "refusal" and resp.parsed_output:
                c = resp.parsed_output
                tags = list(dict.fromkeys(fixed + [t if t.startswith("#") else f"#{t}" for t in c.hashtags]))[:maxh + len(fixed)]
                return {"legenda": c.legenda, "hashtags": tags, "texto_story": c.texto_story,
                        "alt_text": c.alt_text, "narracao": c.narracao, "fonte": "ia"}
        except Exception as e:
            log(f"  ! IA indisponível ({type(e).__name__}: {e}); usando legenda padrão")
    album = _nome_projeto(rows) or "Obra concluída"
    cidade = (perfil.get("cidade") or "Apucarana")
    return {"legenda": random.choice(FALLBACK_TMPL).format(album=album, cidade=cidade),
            "hashtags": fixed,
            "texto_story": random.choice(FALLBACK_STORY_TMPL).format(album=album),
            "alt_text": "", "narracao": "", "fonte": "modelo"}


def full_caption(c: dict) -> str:
    from .site import linha_creditos
    tags = " ".join(c.get("hashtags", []))
    cred = linha_creditos(c.get("creditos") or {})
    return "\n\n".join(x for x in (c["legenda"], cred, tags) if x).strip()
