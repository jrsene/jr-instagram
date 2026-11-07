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
    texto_story: str      # frase curta (até 6 palavras, sem ponto final) para colocar em cima do story
    alt_text: str         # descrição objetiva da imagem, sem adjetivo de propaganda
    narracao: str = ""    # só para reels: 1 a 2 frases faladas em primeira pessoa (narração com a voz dele)


# Legendas de reserva (quando não há IA). Sóbrias, sem bordão, sem pergunta, sem emoji.
FALLBACK = [
    "Luz, material e acabamento no lugar certo.",
    "Espaço pensado até o último detalhe.",
    "Obra concluída com cuidado em cada etapa.",
    "Simplicidade que exige precisão.",
    "Um projeto, do começo ao acabamento.",
]
FALLBACK_STORY = ["Obra concluída", "Detalhe de acabamento", "Execução com precisão", "Projeto entregue", "Arquitetura e execução"]


def _b64(path, size=768) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _contexto(rows) -> str:
    """Nome e descrição do projeto (galeria do site), para a legenda falar da obra certa."""
    from .site import creditos
    c = creditos(rows)
    if not c["albuns"]:
        return ""
    txt = "; ".join(f"{a['album']}: {a['descricao']}".strip(": ") for a in c["albuns"])
    quem = " e ".join(c["nomes_arquitetos"])
    return (f"Projeto: {txt}. " + (f"Projeto de arquitetura de {quem}. " if quem else "") +
            "Pode citar o nome do projeto, sem agradecimentos genéricos; os créditos com @ já entram "
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
                f"Você escreve as legendas do Instagram {perfil.get('handle', '')}. Idioma: {perfil.get('idioma', 'pt-BR')}.\n"
                f"Tom de voz: {perfil.get('voz', '')}\n"
                f"Formato do post: {formato}. As imagens acima vão juntas nesse post.\n"
                + _contexto(rows) +
                "Escreva como um escritório de arquitetura de alto padrão escreveria: sóbrio, preciso, sem exagero.\n"
                "Regras:\n"
                "- Legenda: 1 ou 2 frases curtas descrevendo o que se vê (espaço, luz, material, acabamento, execução).\n"
                "- Não use bordão nem clichê. Evite: 'bora', 'arrasou', 'sonho realizado', 'espaço dos sonhos', "
                "'transformação', 'qualidade que faz a diferença', 'não é só X, é Y', 'a gente registra', "
                "'momento', 'dias bons'.\n"
                "- Sem ponto de exclamação, sem emoji, sem pergunta para engajar, sem pedir para comentar.\n"
                f"- Hashtags: até {maxh}, específicas ao que aparece (ex.: marcenaria, iluminação, porcelanato). "
                "Nada genérico (#love, #instagood, #viral).\n"
                "- Texto do story: até 6 palavras, sem ponto final.\n"
                "- Alt text: descrição objetiva do que aparece na imagem, sem adjetivo de propaganda.\n"
                + ("- Reel: também escreva a narração, 1 ou 2 frases curtas em primeira pessoa, tranquilas, "
                   "como quem descreve o momento sem pressa (até ~12 segundos de fala).\n"
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
    return {"legenda": random.choice(FALLBACK), "hashtags": fixed, "texto_story": random.choice(FALLBACK_STORY),
            "alt_text": "", "narracao": "", "fonte": "modelo"}


def full_caption(c: dict) -> str:
    from .site import linha_creditos
    tags = " ".join(c.get("hashtags", []))
    cred = linha_creditos(c.get("creditos") or {})
    return "\n\n".join(x for x in (c["legenda"], cred, tags) if x).strip()
