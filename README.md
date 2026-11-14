# Saturday

Agente de atendimento autônomo da MEX. Hoje atende portabilidade de empréstimo
INSS → C6; o piloto em construção é o Crédito do Trabalhador (CLT) pela Granatech.

As regras do projeto, o escopo e o critério de pronto de cada fase estão no
[`AGENTS.md`](AGENTS.md). Leia antes de mexer no código.

## Estrutura

```text
apps/core/              pacote Python: API, worker, agente e regras
apps/core/migrations/   Alembic (as migrações pertencem ao pacote, não à raiz)
apps/painel/            painel da equipe: React + Vite + TS, servido por nginx
simuladores/            simuladores dos parceiros (projeto do workspace)
docs/                   índice e decisões registradas (docs/decisoes/)
pyproject.toml, uv.lock workspace `uv`: um lock e um .venv para os dois membros
compose.yaml            deploy (Dokploy): migrate, api, worker e opcionais
compose.override.yaml   desenvolvimento local: publica portas e console do MinIO
AGENTS.md               contrato: regras, arquitetura alvo e fases
```

Desde a Fase 1 o estado das conversas vive no **Postgres**, os anexos no **S3** e
a entrega das respostas passa pelo **outbox**, consumido pelo worker. Não há mais
SQLite nem volume local: a aplicação não escreve em disco.

Desde a Fase 2 existe o **canal WhatsApp** (`apps/core/src/saturday/canais/`):
webhook da Meta que grava e responde 200, fila de eventos processada pelo worker,
mídia no S3, transcrição de áudio e entrega em texto ou modelo conforme a janela
de 24 h. O simulador da Meta vive em `simuladores/meta/` (projeto `uv` próprio).

Desde a Fase 3 existe o **painel da equipe** (`apps/painel/`) e a API admin
(`/admin/*`): login com argon2id, inbox por fila (com a IA, handoff, assumida),
conversa com assumir, devolver, transferir e responder, ficha com dados
mascarados e revelar auditado, alertas e contador de cota, em tempo real por SSE.
Quem responde cada conversa está em `conversas.atendimento`
([decisão 0003](docs/decisoes/0003-estado-de-atendimento-na-tabela-conversas.md));
os termos estão no [`GLOSSARY.md`](GLOSSARY.md). A aba **Granatech** lista
consultas e propostas e deixa o gestor reconciliar, reenviar o link de
biometria, cancelar, corrigir a conta e atualizar o detalhe
([decisão 0013](docs/decisoes/0013-acoes-do-painel-na-granatech-por-turno-de-sistema.md)).
A aba **Agente** (`/admin/agente/*`) desenha o grafo compilado
(`agent/graph.py`, nó a nó com descrição, modelo e passagens em 24 h), lista as
execuções (`turnos`) de todas as conversas ao vivo, com filtro por nó e
situação, duração, erro (só o nome da exceção) e o caminho no grafo, e troca o
modelo de cada etapa em versões com histórico, catálogo da OpenRouter (fonte e
data à vista), comparação e teste
([decisão 0016](docs/decisoes/0016-modelos-do-agente-versionados-no-banco.md)).
No compositor da conversa, o botão de atalhos edita a ficha (nome, nascimento,
sexo, e-mail, celular, CPF e conta, com auditoria só dos nomes dos campos; o CPF
trava depois da consulta e a conta depois da proposta), envia modelo e exporta
a conversa; `/` insere uma **resposta rápida**, cadastrada pelo gestor na tela
Canais. O compositor também envia anexo (JPG e PNG até 5 MB, PDF até 16 MB, por
botão ou arrastando) e áudio gravado no navegador (até 5 min): o arquivo vai cru
para `POST /admin/conversas/{id}/anexos`, fica no S3 e o outbox leva só a chave.
Na Meta o worker sobe a mídia (`/{phone_number_id}/media`) e envia pelo id; o
áudio vira voz (ogg/opus) com o ffmpeg que a imagem do core instala. Na
Evolution, `sendMedia` e `sendWhatsAppAudio` (ver `docs/evolution.md`).

Desde a Fase 4 existe a **camada da Granatech** (`apps/core/src/saturday/bancos/`):
cliente com token em cache e retry só em GET, normalização em `Decimal`, ajuste ao
teto de R$ 6.999, controle de cota, proposta criada uma única vez (com
reconciliação pela listagem), webhook `/webhooks/granatech` e o simulador em
`simuladores/granatech/`. Ver [`docs/granatech.md`](docs/granatech.md).

Desde a Fase 5 existe o **ramo CLT** no grafo (`apps/core/src/saturday/agent/clt/`):
triagem sem gastar cota, empresa pela BrasilAPI, identificação, consentimento com
prova, consulta, escolha de vínculo e oferta; desde a Fase 6, também dados da
proposta, aceite, criação da proposta, formalização e pagamento. Os textos ficam em
`conhecimento/clt/mensagens.yaml`. Ver [`docs/clt.md`](docs/clt.md).

Fora das fases, o **canal Evolution** (`canais/evolution/`): números de WhatsApp
Web pela Evolution API, ao lado da Meta, sem janela nem modelos e desligado por
padrão (`SATURDAY_EVOLUTION_ATIVO`). O gestor cria e conecta as instâncias na
tela **Canais** do painel. Simulador em `simuladores/evolution/`. Ver
[`docs/evolution.md`](docs/evolution.md) e a
[decisão 0009](docs/decisoes/0009-evolution-api-como-segundo-canal-whatsapp.md).

Desde a Fase 7: guia de deploy completo em [`docs/deploy.md`](docs/deploy.md)
(ambiente do zero, backup e restauração), `infra/testar_restauracao.sh` e
as evidências da homologação com a Granatech, geradas pelo gestor na aba
Granatech do painel (ver [`docs/granatech.md`](docs/granatech.md) e a
[decisão 0014](docs/decisoes/0014-homologacao-pelo-painel.md)).

## Rodar local, sem container

Precisa de um Postgres. O mais curto é usar o do compose:

```bash
cp .env.example .env                  # preencha as chaves e as do WhatsApp
docker compose --profile postgres up -d postgres
uv run --project apps/core alembic -c apps/core/alembic.ini upgrade head   # cria as tabelas
uv run --project apps/core saturday
```

Para conversar pelo simulador em vez da Meta, suba-o à parte e aponte a Graph:

```bash
uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100
# SATURDAY_WHATSAPP_GRAPH_URL=http://127.0.0.1:8100 no .env
```

O da Granatech segue o mesmo molde (o compose local já sobe os dois):

```bash
uv run --project simuladores uvicorn app:app --app-dir simuladores/granatech --port 8200
# SATURDAY_GRANATECH_BASE_URL=http://127.0.0.1:8200 e
# SATURDAY_GRANATECH_CHAVE_API=chave-do-simulador no .env
```

E o da Evolution (as instâncias se criam na tela Canais):

```bash
uv run --project simuladores uvicorn app:app --app-dir simuladores/evolution --port 8300
# SATURDAY_EVOLUTION_ATIVO=true, SATURDAY_EVOLUTION_URL=http://127.0.0.1:8300,
# SATURDAY_EVOLUTION_API_KEY=chave-do-simulador,
# SATURDAY_EVOLUTION_WEBHOOK_TOKEN=token-do-simulador no .env
```

Rode **da raiz**: o `pydantic-settings` lê o `.env` do diretório atual, então de
dentro de `apps/core` as chaves não são encontradas e a aplicação não sobe (a
mensagem de erro lista o que falta).

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

O painel roda à parte, com o Vite fazendo proxy de `/admin` para a API local:

```bash
uv run --project apps/core saturday criar-usuario --email voce@mex.com.br --perfil gestor --nome "Seu Nome"
cd apps/painel && npm ci && npm run dev            # http://localhost:5173
```

Para mexer só no painel com os dados do dev, sem subir a API local, aponte o
proxy para ele: `PAINEL_API=https://saturday-dev.dynatech.systems npm run dev`.
Entre com a sua conta do dev, no Chrome ou no Firefox, que aceitam o cookie
`Secure` em `localhost`.

O primeiro gestor só nasce pelo comando; a senha é pedida no terminal (mínimo
de 12 caracteres) e nunca passa por argumento.

## Rodar com Docker

```bash
cp .env.example .env                  # preencha as chaves
docker compose --profile postgres --profile minio up --build
curl -f localhost:8000/health
```

O compose constrói a imagem a partir da raiz (`apps/core/Dockerfile`) e sobe, em
ordem: `postgres` → `migrate` (roda o Alembic e termina) → `api`, `worker` e
`painel`. O `compose.override.yaml` publica as portas `8000` (API), `5173`
(painel), `5432` (Postgres), `9000`/`9001` (MinIO e console). Crie o primeiro
gestor com `docker compose exec api saturday criar-usuario --email ... --perfil gestor`;
os demais usuários, o gestor cadastra na aba **Usuários** do painel
(docs/decisoes/0012).

O contêiner `painel` (nginx) serve o build do Vite e faz proxy de `/admin/` para
a `api`: painel e API ficam na mesma origem, sem CORS, e o cookie de sessão é
`HttpOnly`, `SameSite=Strict` e `Secure` fora de `dev`. No Dokploy, o domínio do
painel aponta para o serviço `painel`.

Com `SATURDAY_WEBHOOK_URL` definida, `POST /chat` responde `202` e a resposta sai
pelo worker: ele entrega o outbox, com backoff (2 s, 4 s, 8 s…) até
`SATURDAY_OUTBOX_MAX_TENTATIVAS`. Sem URL de webhook, a resposta volta na própria
requisição.

### `.env.local` (opcional)

O compose lê `.env` e, se existir, `.env.local` por cima. Use o segundo para o
que muda por máquina (URL do Postgres, endpoint do S3) sem mexer no `.env`
compartilhado. Ele é ignorado pelo git (`.env.*`).

## Desenvolvimento

```bash
uv sync --locked                      # na raiz: ambiente único do workspace
cd apps/core
uv run ruff format --check            # formatação
uv run ruff check                     # lint
uv run mypy                           # tipos
uv run pytest -q                      # testes sem Postgres (os de banco são pulados)
```

Os testes que exercitam o backend real (trava consultiva, poda de checkpoints,
outbox, sobrevivência ao restart) exigem um Postgres **de teste**:

```bash
docker compose --profile postgres up -d postgres
docker exec saturday-postgres-1 createdb -U saturday saturday_test
SATURDAY_TEST_DATABASE_URL='postgresql://saturday:saturday@127.0.0.1:5432/saturday_test' \
  uv run pytest -q
```

O nome do banco precisa conter `test`: os fixtures apagam e recriam as tabelas, e
a suíte recusa um banco que não se declare descartável.

Os mesmos comandos rodam no CI (`.github/workflows/tests.yml`) a cada push e
pull request.

## Contrato da API

O contrato completo (`/chat`, rotas de conversa, retenção do extrato e
verificação de assinatura do webhook) está em
[`apps/core/README.md`](apps/core/README.md).
