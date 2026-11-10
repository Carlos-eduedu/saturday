# Saturday

Agente de atendimento autônomo da MEX. Hoje atende portabilidade de empréstimo
INSS → C6; o piloto em construção é o Crédito do Trabalhador (CLT) pela Granatech.

As regras do projeto, o escopo e o critério de pronto de cada fase estão no
[`AGENTS.md`](AGENTS.md). Leia antes de mexer no código.

## Estrutura

```text
apps/core/          pacote Python (`uv`): API, agente LangGraph e regras
compose.yaml        deploy (Dokploy): sem portas, volumes nomeados, limites
compose.override.yaml   desenvolvimento local: publica a porta 8000
AGENTS.md           contrato: regras, arquitetura alvo e fases
```

`migrations/`, `simuladores/`, `infra/`, `regras/`, `conhecimento/` e
`apps/painel/` entram nas fases que colocarem neles o primeiro arquivo real
(1 a 5), conforme o `AGENTS.md`.

## Rodar local, sem container

```bash
cp .env.example .env                  # preencha as chaves do OpenRouter
uv run --project apps/core saturday
```

Rode **da raiz**: o `pydantic-settings` lê o `.env` do diretório atual, então de
dentro de `apps/core` as chaves não são encontradas e a aplicação não sobe (a
mensagem de erro lista o que falta). Os checkpoints ficam em `./data`, como antes
do monorepo.

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

## Rodar com Docker

```bash
cp .env.example .env                  # preencha as chaves
docker compose up --build
curl -f localhost:8000/health
```

O compose constrói a imagem com contexto `apps/core` e persiste os checkpoints
no volume nomeado `dados`, montado em `/app/data`. O `compose.override.yaml`
publica a porta `8000` no local.

## Desenvolvimento

```bash
cd apps/core
uv run ruff format --check            # formatação
uv run ruff check                     # lint
uv run mypy                           # tipos
uv run pytest -q                      # testes, sem rede
```

Os mesmos comandos rodam no CI (`.github/workflows/tests.yml`) a cada push e
pull request.

## Contrato da API

O contrato completo (`/chat`, rotas de conversa, retenção do extrato e
verificação de assinatura do webhook) está em
[`apps/core/README.md`](apps/core/README.md).
