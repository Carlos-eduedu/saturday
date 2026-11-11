# Saturday

Agente de atendimento independente para portabilidade de empréstimos INSS → C6.

## Rodar local

Este pacote é um app do monorepo `saturday`. Rode **da raiz do repositório**, onde
fica o `.env`, e com um Postgres disponível:

```bash
cp .env.example .env   # preencha as chaves e modelos do OpenRouter
docker compose --profile postgres up -d postgres
uv run --project apps/core alembic upgrade head
uv run --project apps/core saturday
```

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

## Rodar com Docker

```bash
cp .env.example .env   # preencha as chaves e modelos
docker compose --profile postgres --profile minio up --build
```

O serviço `migrate` roda o Alembic e termina; `api` e `worker` só sobem depois
disso. A aplicação não escreve em disco: o estado vai para o Postgres e os
anexos para o S3.

## Migrações

As migrações ficam em `migrations/`, dentro deste pacote, porque são os modelos
deste pacote que elas descrevem:

```bash
uv run alembic upgrade head      # aplica
uv run alembic revision --autogenerate -m "descrição"
```

`alembic.ini` lê a URL de `SATURDAY_DATABASE_URL` (ver `migrations/env.py`), então
o mesmo arquivo serve para dev, homolog e produção.

## Worker

`saturday-worker` consome o `outbox` e entrega os envios ao canal. A API grava a
resposta na mesma transação do turno e nunca fala com o canal: um envio que falha
volta para a fila com backoff, sem prender a resposta ao cliente.

## Variáveis de ambiente

Todas usam o prefixo `SATURDAY_`. O `.env` é lido automaticamente.

| Variável | Padrão | Descrição |
|---|---|---|
| `SATURDAY_ENVIRONMENT` | `dev` | `dev`, `prod` ou `pytest` (pytest desliga as validações obrigatórias). |
| `SATURDAY_LOG_LEVEL` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `SATURDAY_API_KEY` | vazio | Chave esperada no header `X-API-Key`; obrigatória em `prod`. |
| `SATURDAY_OPENROUTER_API_KEY` | vazio | Chave da API do OpenRouter; obrigatória fora de `pytest`. |
| `SATURDAY_LLM_MODEL` | vazio | Slug do modelo de texto para dúvidas. |
| `SATURDAY_VISION_MODEL` | vazio | Slug do modelo de visão para ler o extrato. |
| `SATURDAY_JEV_MODEL` | `typesafe/jev-1.13` | Modelo do Jev; mantenha fixo para a calibração valer. |
| `SATURDAY_WEBHOOK_URL` | vazio | URL do webhook de saída; vazio = responde na própria requisição. |
| `SATURDAY_WEBHOOK_SECRET` | vazio | Segredo HMAC-SHA256; obrigatório se `WEBHOOK_URL` existir. |
| `SATURDAY_ANEXO_DOMINIOS` | vazio | Domínios permitidos para anexos por URL, separados por vírgula; vazio = só base64. |
| `SATURDAY_DATABASE_URL` | vazio | Postgres do estado das conversas, outbox e travas. Obrigatório fora de `pytest`. |
| `SATURDAY_S3_ENDPOINT` | vazio | Endpoint do S3 (vazio = MinIO do compose). |
| `SATURDAY_S3_BUCKET` | vazio | Bucket dos anexos. Obrigatório com Postgres. |
| `SATURDAY_S3_ACCESS_KEY`, `SATURDAY_S3_SECRET_KEY` | vazio | Credenciais do S3. |
| `SATURDAY_OUTBOX_MAX_TENTATIVAS` | `8` | Tentativas de entrega antes de desistir. |
| `SATURDAY_OUTBOX_BACKOFF_BASE_S` | `2.0` | Espera inicial do backoff (dobra a cada falha). |
| `SATURDAY_RETENCAO_EXTRATO_DIAS` | `30` | Dias de retenção do extrato; ao expirar, o extrato é apagado no próximo turno. |
| `SATURDAY_HANDOFF_AUTO_RELEASE_HORAS` | `0` | Horas para liberar automaticamente um handoff; `0` desliga. |

> **Atenção:** todas as variáveis de ambiente agora usam o prefixo `SATURDAY_`.
> Por exemplo, `OPENROUTER_API_KEY` virou `SATURDAY_OPENROUTER_API_KEY`,
> `LLM_MODEL` virou `SATURDAY_LLM_MODEL` e `WEBHOOK_URL` virou
> `SATURDAY_WEBHOOK_URL`.

Sem `SATURDAY_OPENROUTER_API_KEY` (ou sem `SATURDAY_LLM_MODEL` /
`SATURDAY_VISION_MODEL`), a aplicação não sobe fora do ambiente `pytest`.

## Contrato da API

### `GET /health`

Aberto, sem autenticação. Responde `{"status": "ok"}`.

### `POST /chat`

Headers: `X-API-Key` (obrigatório em `prod`) e `Content-Type: application/json`.

Corpo:

```json
{
  "conversation_id": "abc123",
  "message_id": "msg-001",
  "message": "Quero portabilidade",
  "attachments": [{"mime_type": "application/pdf", "url": "https://..."}]
}
```

- `conversation_id`: 1 a 128 caracteres; `^[A-Za-z0-9_.:@+\-]+$`.
- `message_id` (opcional): 1 a 128 caracteres; repetir o mesmo `message_id` devolve `status="duplicate"` sem rodar o grafo.
- `message`: no máximo 4.000 caracteres.
- `attachments`: no máximo 10 itens; cada item aceita `url` **ou** `base64`, nunca os dois.
- `mime_type`: `application/pdf`, `image/jpeg`, `image/png` ou `image/webp`.

Respostas:

| Situação | Status HTTP | Corpo |
|---|---|---|
| Resposta síncrona | 200 | `{conversation_id, status, answer, handoff_reason, portability_result}` |
| `message_id` repetido | 200 | `{conversation_id, status: "duplicate", answer: ""}` |
| Webhook configurado | 202 | `{conversation_id, status: "accepted"}` |
| Handoff | 200 | `status="with_human"` e `handoff_reason` preenchido |
| Sem API key (prod) | 401 | `{"detail": "não autorizado"}` |

`status` pode ser `answered`, `with_human` ou `duplicate`.
`handoff_reason` pode ser `sem_resposta`, `sem_portabilidade`,
`dados_cliente_nao_informados`, `idade_fora_regra`, `idade_prazo_96`,
`especie_nao_atendida`, `extrato_ilegivel` ou `erro_interno`.

### Rotas de conversa

Protegidas por `X-API-Key` (quando configurada em `prod`).

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/conversations/{conversation_id}` | Estado da conversa (sem mensagens, extrato ou dados do cliente). |
| `POST` | `/conversations/{conversation_id}/release` | Libera um handoff e devolve a conversa ao agente. |
| `DELETE` | `/conversations/{conversation_id}` | Apaga a conversa inteira (pedidos de exclusão — LGPD). |

O `GET` devolve `{conversation_id, status, handoff_reason, handoff_em, oferta_pendente, aguardando}`.
O `DELETE` devolve `204`. O `release` devolve `{conversation_id, status: "in_progress"}`.

### Política de retenção do extrato

O extrato é guardado por no máximo `SATURDAY_RETENCAO_EXTRATO_DIAS` dias
(padrão: 30). No início de cada turno, se o extrato recebido estiver mais antigo
que isso, ele é apagado do estado junto com o resultado de portabilidade e a
oferta pendente. O `DELETE` remove a conversa inteira imediatamente.

## Verificação da assinatura do webhook

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

## Testes

```bash
uv run pytest
```

Os testes não fazem chamadas reais ao OpenRouter, downloads ou webhooks.

## Estrutura

- `agent/`: grafo LangGraph, estado e nós.
- `portabilidade/`: regras, cálculo, leitura do Hiscon e mensagens fixas.
- `services/`: OpenRouter (Jev/visão/texto), anexos e webhook.

## Canal WhatsApp

Arquivos em `canais/whatsapp/`. O caminho de uma mensagem:

1. `GET /webhooks/whatsapp` responde o desafio da Meta (uma vez, no cadastro).
2. `POST /webhooks/whatsapp` valida `X-Hub-Signature-256` (HMAC-SHA256 do corpo
   cru, comparação em tempo constante), grava o evento em `eventos_recebidos` e
   responde 200. O turno **não** roda aqui: a Meta reenvia quando demora.
3. O worker reivindica o evento, roda o turno sob a trava da conversa e grava a
   resposta no `outbox`.
4. O worker entrega pelo canal: janela de 24 h aberta → texto dividido por linha
   em branco (até 5 partes, 0,9 s entre elas); fechada → modelo `atualizacao_pedido`.

Mídia: dois passos (`GET /{media_id}` e depois a URL devolvida), limite de 50 MB,
guardada em `whatsapp/{telefone}/{wamid}.{ext}`. Foto e PDF até 4,5 MB seguem como
anexo do grafo; áudio é transcrito (endpoint compatível com OpenAI) e, se a
transcrição falhar, o cliente recebe o pedido para escrever.

Autenticação de saída: `Authorization: Bearer SATURDAY_WHATSAPP_TOKEN`. Retry com
esperas de 2 s, 5 s e 10 s só em erro temporário (5xx, timeout e os códigos
listados em `canais/whatsapp/cliente.py`); esgotado, o outbox reentrega depois.

O simulador da Meta fica em `simuladores/meta/` e cobre envio, download de mídia
e injeção de mensagem assinada:

```bash
uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100
```
