"""Publica um vídeo ou foto avulsa com legenda própria, sem mexer na seleção do piloto automático.

Uso (só roda no workflow manual "publicar-avulso"; por padrão não publica, só prepara):
  python -m autopost.avulso --midia posts/comfy-antes-depois/video.mp4 \
      --legenda posts/comfy-antes-depois/legenda.txt [--publicar]

Sem --publicar, gera a prévia em output/avulso/ e não chama a API do Instagram.
"""
import argparse
import shutil
import sys
from pathlib import Path

from .publisher import Publisher

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autopost.avulso")
    ap.add_argument("--midia", required=True, help="caminho do .mp4 (ou .jpg) dentro do repositório")
    ap.add_argument("--legenda", required=True, help="arquivo .txt com a legenda final (hashtags incluídas)")
    ap.add_argument("--publicar", action="store_true", help="publica de verdade no Instagram")
    ap.add_argument("--reel", action="store_true", help="publica o vídeo como reel (REELS), em vez de post de vídeo")
    a = ap.parse_args(argv)

    midia = (ROOT / a.midia).resolve()
    legenda = (ROOT / a.legenda).read_text(encoding="utf-8").strip()
    if not midia.exists():
        sys.exit(f"Arquivo não encontrado: {midia}")
    if not legenda:
        sys.exit("A legenda está vazia.")
    if "[PREENCHER" in legenda:
        sys.exit("A legenda ainda tem um campo [PREENCHER]. Preencha antes de publicar.")

    destino = ROOT / "output" / "avulso" / midia.name
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(midia, destino)
    tipo = "video" if destino.suffix.lower() == ".mp4" else "foto"
    print(f"mídia: {destino} ({tipo})")
    print(f"legenda:\n{legenda}\n")

    if not a.publicar:
        print("Prévia pronta. Nada foi publicado (faltou --publicar).")
        return
    pub = Publisher({}, ROOT)
    if a.reel and tipo != "video":
        sys.exit("--reel só vale para vídeo .mp4")
    ptipo = "reel" if a.reel else ("video" if tipo == "video" else "feed")
    igid = pub.publish(ptipo, [destino], legenda)
    print(f"publicado: id {igid}")


if __name__ == "__main__":
    main()
