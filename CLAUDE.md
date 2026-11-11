# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

O contrato do projeto (regras inegociáveis, escopo, fases, especificações da
Granatech, da jornada CLT e do WhatsApp) está no `AGENTS.md`, importado abaixo.
Ele vale integralmente; este arquivo só acrescenta o mapa do código atual.

@AGENTS.md

## Comandos do dia a dia

O workspace `uv` tem um único `uv.lock` e um único `.venv` na raiz
(membros: `apps/core` e `simuladores`). Lint, tipos e testes rodam de dentro do
membro; o servidor roda da raiz (o `.env` é lido do diretório atual).

```bash
cd apps/core
uv run pytest tests/test_outbox.py -q                 # um arquivo
uv run pytest tests/test_whatsapp.py::nome_do_teste   # um teste
uv run pytest -k janela -q                            # por nome
uv run ruff check --fix && uv run ruff format         # corrige estilo

cd simuladores && uv run ruff check && uv run mypy    # o CI também cobre os simuladores

# simulador da Meta (aponte SATURDAY_WHATSAPP_GRAPH_URL para ele)
uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100
```

- `pytest` roda com `filterwarnings = error`: qualquer warning novo quebra a suíte.
- Testes marcados `jev` chamam o classificador de verdade e são pulados sem
  `SATURDAY_OPENROUTER_API_KEY`.
- Com `environment == "pytest"` o checkpointer é `InMemorySaver` e o storage é
  `MemoriaStorage` (também sem `S3_BUCKET`); sem `SATURDAY_TEST_DATABASE_URL`, os testes de Postgres
  (trava, outbox, poda de checkpoints, retenção) são pulados — rode-os antes de
  dar uma fase por pronta.
- mypy é `strict` e só cobre `src/saturday`.
- Há `.env` e `.env.backup` reais na raiz: não leia. Use o `.env.example`.

## Arquitetura (o que exige ler vários arquivos)

**Duas entradas, mesma montagem.** `saturday` (API, `web/application.py`) e
`saturday-worker` (`worker.py`) montam as mesmas dependências por
`web/composicao.py` (`criar_servico`, `criar_checkpointer`,
`criar_canal_whatsapp`). Ao adicionar um cliente ou canal, ligue-o ali para que
os dois processos o recebam. `web/lifespan.py` cuida só de abrir e fechar.

**Caminho de uma mensagem do WhatsApp:**

1. `web/api/whatsapp.py` valida a assinatura, grava em `eventos_recebidos`
   (`dados/eventos.py`, deduplicado por `wamid`) e responde 200.
2. O worker, em um único laço, chama `jobs/eventos.processar` (evento → turno ou
   atualização de status) e `jobs/outbox.drenar` (entrega).
3. `canais/whatsapp/entrada.py` normaliza o evento (mídia para o S3,
   transcrição de áudio) em um `ChatRequest` e chama `AgentService`.
4. `agent/service.py` é o orquestrador: abre a sessão, pega
   `pg_advisory_xact_lock` da conversa (`dados/trava.py`), roda o grafo, grava a
   resposta em `mensagens` e no `outbox` **na mesma transação**. Também trata
   `message_id` repetido, handoff, retenção e poda de checkpoints.
5. `jobs/outbox.py` entrega por `EntregadorPorCanal` (`whatsapp` ou `webhook`).
   O canal só **classifica** o resultado (`ok`, `temporario`,
   `temporario_incerto`, `permanente`, `janela_fechada`); reagendar é só do
   outbox — ver `docs/decisoes/0001-outbox-dono-do-reagendamento.md`. Não
   coloque retry dentro de um canal.

O `POST /chat` (contrato HTTP antigo, documentado em `apps/core/README.md`) usa o
mesmo `AgentService`: com `SATURDAY_WEBHOOK_URL` responde 202 e a resposta sai
pelo outbox; sem ela, volta na própria requisição.

**Grafo (`agent/`).** `graph.py` monta o `StateGraph`; `nodes.py` tem os nós,
`routing.py` as decisões de aresta (determinísticas), `state.py` o estado,
`context.py` os clientes injetados (`jev`, `llm`, `anexos`) e `textos.py` os
textos fixos. Hoje só existe o ramo INSS → C6, cujas regras e cálculos ficam em
`portabilidade/` (`hiscon.py` lê o extrato, `calculo.py` e `regras.py` decidem).
O estado guarda só a chave do anexo no storage, nunca o conteúdo.

**IA (`services/`).** `jev.py` é o classificador de intenção/público; `llm.py`
responde dúvidas ancoradas na FAQ (`faq.py`); `anexos.py` lê foto/PDF por modelo
de visão; tudo via OpenRouter. Os testes trocam esses clientes por falsos em
`tests/conftest.py` (`resultado_jev`, `FakeJev`, etc.) — reaproveite-os.

**Dados (`dados/`).** SQLAlchemy em `modelos.py`, consultas em
`repositorios.py`, sessão em `sessao.py`. Migrações Alembic ficam em
`apps/core/migrations/` (não na raiz); toda mudança em `modelos.py` precisa de
uma migração nova.

**Configuração.** `settings.py` (`pydantic-settings`, prefixo `SATURDAY_`);
`validar_para_subir()` derruba a subida se faltar segredo obrigatório no
ambiente. Variável nova entra também no `.env.example`.

**Decisões registradas** ficam em `docs/decisoes/NNNN-*.md`; registre ali
qualquer desvio consciente do `AGENTS.md`.
