# Saturday

Agente de atendimento independente para portabilidade de empréstimos INSS → C6.

## Rodar local

```bash
cp .env.example .env   # preencha as chaves e modelos do OpenRouter
uv run saturday
```

A API sobe em `http://localhost:8000` (`GET /health`, `POST /chat`, docs em `/docs`).
Os logs saem em JSON, uma linha por registro.

## Rodar com Docker

```bash
cp .env.example .env   # preencha as chaves e modelos
docker compose up --build
```

O serviço `saturday` lê o `.env`, expõe a porta `8000` e persiste os checkpoints
em `./data`. O volume `./data:/app/data` mantém as conversas mesmo depois de
`docker compose restart` (ou `down`, desde que o volume não seja removido).

> **Permissão do volume:** em Linux, o Docker pode criar `./data` como root.
> O entrypoint do container ajusta a permissão de `/app/data` e depois executa
> a aplicação como `saturday` (UID 1000). Se o seu ambiente bloquear `chown` no
> volume, crie o diretório antes (`mkdir -p data`) com escrita para o UID 1000
> ou aponte `SATURDAY_CHECKPOINT_PATH` para um caminho gravável. O erro
> `unable to open database file` indica exatamente esse problema.

> **Atenção:** a aplicação roda com **1 worker** porque o estado das conversas
> vive no SQLite local (`SATURDAY_CHECKPOINT_PATH`). Não aumente o número de
> workers sem migrar a persistência para um backend compartilhado.

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
| `SATURDAY_CHECKPOINT_PATH` | `data/checkpoints.sqlite` | Arquivo SQLite dos checkpoints das conversas. |
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
