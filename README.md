# Piloto automático do Instagram

Pega todas as suas fotos e vídeos, escolhe as melhores, monta posts, montagens, carrosséis, stories e reels, escreve a legenda com IA e publica sozinho nos horários definidos.

## Como funciona

0. **OneDrive** (`autopost/onedrive.py`): lê o Álbum da Câmera (Upload da Câmera do iPhone) e outras pastas, pegando uma versão de 1800px sem baixar os originais. Fotos repetidas entre iPhone, PC, Mac e Drive são detectadas e entram uma vez só.
0b. **Google Drive** (`autopost/drive.py`): baixa fotos e vídeos novos das pastas listadas em `drive.pastas`.
1. **Catálogo** (`autopost/library.py`): tudo que cair nas pastas de `fontes` (padrão `inbox/`) é catalogado. Lê JPG, PNG, HEIC (iPhone), DNG (RAW) e MP4/MOV. Cada foto ganha uma nota de qualidade (nitidez e exposição), e as borradas ou escuras ficam de fora.
1b. **Curadoria com IA** (`autopost/curate.py`): o Claude olha cada foto nova e reprova prints, documentos, fotos acidentais, borradas ou íntimas, e marca tags (praia, amigos, comida…). Dá para adicionar critérios seus em `curadoria.extra`.
2. **Escolha**: prioriza fotos novas e nunca usadas, não repete a mesma foto antes de 45 dias e, para montagens e carrosséis, junta fotos do mesmo dia (mesmo rolê). Se faltar conteúdo inédito, reaproveita o que foi usado há mais tempo.
3. **Montagem** (`autopost/compose.py`):
   - feed em 4:5 (1080×1350) com recorte inteligente, que procura onde está o assunto em vez de cortar sempre no centro;
   - montagens com 2 a 6 fotos em vários layouts, com a melhor foto na célula maior;
   - carrossel com capa em montagem e as fotos depois;
   - story 9:16 com fundo desfocado, cantos arredondados, sombra e frase curta;
   - reel feito de fotos (zoom suave, transições e música opcional de `assets/music/`) ou a partir dos seus vídeos.
4. **Legenda** (`autopost/captions.py`): o Claude olha as fotos e escreve a legenda, as hashtags, a frase do story e o texto alternativo no tom definido em `config.yaml`. Sem chave de API, usa frases prontas.
5. **Publicação** (`autopost/publisher.py`): usa a API oficial do Instagram, então não há risco de bloqueio por automação.

## Modos (em `config.yaml`)

| modo | o que faz |
|---|---|
| `dry_run` | gera tudo e a prévia, sem publicar nada (**padrão**) |
| `approve` | gera e deixa pendente; você aprova com `python -m autopost approve all` |
| `auto` | publica sozinho |

## Comandos

```bash
pip install -r requirements.txt     # também precisa de ffmpeg
python -m autopost run              # rotina completa (o que o agendador roda)
python -m autopost plan --dias 7    # gera a semana inteira de uma vez
python -m autopost preview          # abre output/preview.html para revisar
```

## Para ligar de verdade

1. **Conta do Instagram Profissional** (Criador ou Empresa).
2. **App na Meta** (developers.facebook.com) com o produto "Instagram API with Instagram Login" e a permissão `instagram_business_content_publish`. Gere um token de longa duração. Ele vale 60 dias e pode ser renovado.
3. **Repositório no GitHub** com esta pasta. Em Settings → Secrets, cadastre `IG_USER_ID`, `IG_ACCESS_TOKEN`, `ANTHROPIC_API_KEY` e `GDRIVE_SA_JSON` (conta de serviço do Google com acesso de leitor às pastas do Drive). O workflow `.github/workflows/autopost.yml` roda nos horários dos posts.
4. **Privacidade:** o repositório é público, mas nada pessoal fica aberto nele. Catálogo, cópias das fotos e posts pendentes ficam criptografados em `state.enc` (chave `STATE_KEY`, gerada com `python -m autopost.state key`). Só aparece em `media/` o que acabou de ser publicado no Instagram.
5. A API do Instagram só aceita arquivos com **link público**. Com `hospedagem: github`, os arquivos gerados sobem para a pasta `media/` do próprio repositório, que precisa ser público. A alternativa é `url_prefix`, apontando para um site ou bucket onde você sincroniza `output/`.

Limites da API: 100 posts publicados a cada 24 horas. Stories pela API não aceitam figurinhas, enquetes nem links.
