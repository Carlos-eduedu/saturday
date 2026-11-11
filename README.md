# Saturday

Agente de atendimento autônomo da MEX. Hoje atende portabilidade de empréstimo
INSS → C6; o piloto em construção é o Crédito do Trabalhador (CLT) pela Granatech.

As regras do projeto, o escopo e o critério de pronto de cada fase estão no
[`AGENTS.md`](AGENTS.md). Leia antes de mexer no código.

## Estrutura

```text
apps/core/              pacote Python (`uv`): API, worker, agente e regras
apps/core/migrations/   Alembic (as migrações pertencem ao pacote, não à raiz)
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

`infra/`, `regras/`, `conhecimento/` e `apps/painel/` entram nas fases que
colocarem neles o primeiro arquivo real (3 a 7).

## Rodar local, sem container

Precisa de um Postgres. O mais curto é usar o do compose:

```bash
cp .env.example .env                  # preencha as chaves e as do WhatsApp
docker compose --profile postgres up -d postgres
uv run --project apps/core alembic upgrade head   # cria as tabelas
uv run --project apps/core saturday
```

Para conversar pelo simulador em vez da Meta, suba-o à parte e aponte a Graph:

```bash
uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100
# SATURDAY_WHATSAPP_GRAPH_URL=http://127.0.0.1:8100 no .env
```

Rode **da raiz**: o `pydantic-settings` lê o `.env` do diretório atual, então de
dentro de `apps/core` as chaves não são encontradas e a aplicação não sobe (a
mensagem de erro lista o que falta).

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

## Rodar com Docker

```bash
cp .env.example .env                  # preencha as chaves
docker compose --profile postgres --profile minio up --build
curl -f localhost:8000/health
```

O compose constrói a imagem a partir da raiz (`apps/core/Dockerfile`) e sobe, em
ordem: `postgres` → `migrate` (roda o Alembic e termina) → `api` e `worker`.
O `compose.override.yaml` publica as portas `8000` (API), `5432` (Postgres),
`9000`/`9001` (MinIO e console).

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
