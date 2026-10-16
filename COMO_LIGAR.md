# Como ligar o piloto (uma vez só)

Tudo é feito no site do GitHub, em **jrsene/jr-instagram → Settings → Secrets and variables → Actions → New repository secret**.
Os segredos ficam protegidos: ninguém vê, nem quem abre o repositório.

## 1. Chave do cofre — `STATE_KEY`
Use a chave que o Claude mandou na conversa. Ela tranca o catálogo de fotos, que é guardado criptografado no repositório.

## 2. IA das legendas e da curadoria — `ANTHROPIC_API_KEY`
console.anthropic.com → API Keys → Create Key. É pago por uso; legendas e curadoria custam poucos centavos por dia.
Sem essa chave o piloto funciona, mas usa frases prontas e só um filtro simples.

## 3. OneDrive — `ONEDRIVE_CLIENT_ID`
1. Entre em portal.azure.com com a **mesma conta Microsoft do OneDrive**.
2. Procure **App registrations** → **New registration**.
   - Nome: `jr-instagram`
   - Supported account types: **Personal Microsoft accounts only**
   - Register.
3. No menu da esquerda, **Authentication** → **Allow public client flows** = **Yes** → Save.
4. Volte em **Overview** e copie o **Application (client) ID**. Esse é o `ONEDRIVE_CLIENT_ID`.
5. No GitHub: aba **Actions** → **conectar-onedrive** → **Run workflow**. Abra a execução e o passo que roda o login:
   aparece um link da Microsoft e um código. Abra o link, digite o código e entre na sua conta. Pronto.

## 4. Instagram — `IG_USER_ID` e `IG_ACCESS_TOKEN`
1. developers.facebook.com → **My Apps** → **Create app** → caso de uso **Gerenciar mensagens e conteúdo no Instagram**.
2. Em **API setup with Instagram login** → **Generate access tokens** → **Add account** → entre com o **@jr.prs**.
3. Copie o **token** (vira `IG_ACCESS_TOKEN`) e o **ID** numérico da conta que aparece ao lado (vira `IG_USER_ID`).
   O piloto renova esse token sozinho a cada semana, então você não precisa voltar aqui.

## 5. Testar
Aba **Actions** → **autopost** → **Run workflow**. Ele começa em modo de teste (`mode: dry_run` no `config.yaml`):
monta tudo, mas não publica. Quando estiver tudo certo, troque para `approve` ou `auto`.
