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

## Verificação da assinatura do webhook

O `POST /chat` também aceita o header `X-API-Key` (obrigatório em produção).
O webhook de saída envia `X-Saturday-Timestamp` (segundos Unix) e
`X-Saturday-Signature` (`sha256=` + HMAC-SHA256 de `timestamp + "." + corpo`,
com `SATURDAY_WEBHOOK_SECRET`). Verifique antes de confiar no evento:

```python
import hashlib
import hmac


def assinatura_valida(corpo: bytes, timestamp: str, recebida: str, segredo: str) -> bool:
    esperado = hmac.new(
        segredo.encode(), f"{timestamp}.".encode() + corpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(recebida, f"sha256={esperado}")
```
