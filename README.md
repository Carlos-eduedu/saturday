# Saturday

Agente de atendimento independente para portabilidade de empréstimos INSS → C6.

## Rodar

```bash
cp .env.example .env   # preencha as chaves e modelos do OpenRouter
uv run saturday
```

> **Atenção:** todas as variáveis de ambiente agora usam o prefixo `SATURDAY_`.
> Por exemplo, `OPENROUTER_API_KEY` virou `SATURDAY_OPENROUTER_API_KEY`,
> `LLM_MODEL` virou `SATURDAY_LLM_MODEL` e `WEBHOOK_URL` virou
> `SATURDAY_WEBHOOK_URL`. O arquivo `.env` é lido automaticamente.

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

Sem `SATURDAY_WEBHOOK_URL`, o `POST /chat` responde na própria requisição. Com
`SATURDAY_WEBHOOK_URL`, responde `202 accepted` e envia o evento `agent.reply`
para o webhook em background.

Sem `SATURDAY_OPENROUTER_API_KEY` (ou sem `SATURDAY_LLM_MODEL` /
`SATURDAY_VISION_MODEL`), a aplicação não sobe fora do ambiente `pytest`.

## Testes

```bash
uv run pytest
```

Os testes não fazem chamadas reais ao OpenRouter, downloads ou webhooks.

## Estrutura

- `agent/`: grafo LangGraph, estado e nós.
- `portabilidade/`: regras, cálculo, leitura do Hiscon e mensagens fixas.
- `services/`: OpenRouter (Jev/visão/texto), anexos e webhook.
