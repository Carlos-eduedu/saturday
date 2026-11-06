# Saturday

Agente de atendimento independente para portabilidade de empréstimos INSS → C6.

## Rodar

```bash
cp .env.example .env   # preencha as chaves e modelos do OpenRouter
uv run --env-file .env saturday
```

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).

Sem `WEBHOOK_URL`, o `POST /chat` responde na própria requisição. Com `WEBHOOK_URL`,
responde `202 accepted` e envia o evento `agent.reply` para o webhook em background.

## Testes

```bash
uv run pytest
```

Os testes não fazem chamadas reais ao OpenRouter, downloads ou webhooks.

## Estrutura

- `agent/`: grafo LangGraph, estado e nós.
- `portabilidade/`: regras, cálculo, leitura do Hiscon e mensagens fixas.
- `services/`: OpenRouter (Jev/visão/texto), anexos e webhook.
