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


FALLBACK = [
    "Guardando esse momento por aqui.",
    "Pequenos recortes de dias bons.",
    "Do jeito que foi, sem filtro de humor.",
    "Mais um capítulo pra coleção.",
    "Quando a vida acontece, a gente registra.",
]
FALLBACK_STORY = ["Bom dia por aqui", "Olha isso", "Recortes da semana", "Momento do dia", "Você já viu?"]


def _b64(path, size=768) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return base64.standard_b64encode(buf.getvalue()).decode()


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
                "Escreva uma legenda curta e natural (1 a 3 frases, pode ter uma pergunta para engajar), "
                f"até {maxh} hashtags específicas ao que aparece (nada genérico tipo #love), "
                "um texto bem curto para o story e um alt text descritivo. "
                "Não invente nomes de lugares ou pessoas que não dá para ver nas fotos.")})
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
                        "alt_text": c.alt_text, "fonte": "ia"}
        except Exception as e:
            log(f"  ! IA indisponível ({type(e).__name__}: {e}); usando legenda padrão")
    return {"legenda": random.choice(FALLBACK), "hashtags": fixed, "texto_story": random.choice(FALLBACK_STORY),
            "alt_text": "", "fonte": "modelo"}


def full_caption(c: dict) -> str:
    tags = " ".join(c.get("hashtags", []))
    return f"{c['legenda']}\n\n{tags}".strip()
