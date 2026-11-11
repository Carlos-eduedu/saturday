# Saturday

Agente de atendimento independente para portabilidade de empréstimos INSS → C6.

## Rodar local

Este pacote é um app do monorepo `saturday`. Rode **da raiz do repositório**, onde
fica o `.env`, e com um Postgres disponível:

```bash
cp .env.example .env   # preencha as chaves e modelos do OpenRouter
docker compose --profile postgres up -d postgres
uv run --project apps/core alembic -c apps/core/alembic.ini upgrade head
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

`saturday-worker` processa a fila de eventos (WhatsApp e Granatech), verifica os
alertas de tempo e consome o `outbox`, entregando os envios ao canal. A API grava a
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
| `SATURDAY_HANDOFF_AUTO_RELEASE_HORAS` | `0` | Horas para liberar automaticamente um handoff sem dono; `0` desliga. Conversa assumida nunca é liberada sozinha. |
| `SATURDAY_SESSAO_SEGREDO` | vazio | Assina o CSRF do painel. Obrigatória fora de `pytest`. |
| `SATURDAY_GRANATECH_BASE_URL` | api-dev | Base da API da Granatech; em dev, o simulador (`http://granatech:8200`). |
| `SATURDAY_GRANATECH_CHAVE_API` | vazio | Chave do login. Obrigatória com `GRANATECH_ATIVO=true`. |
| `SATURDAY_GRANATECH_WEBHOOK_TOKEN` | vazio | Token do webhook. Sem ele, `/webhooks/granatech` responde 503; obrigatória em `homolog` e `prod` e com `GRANATECH_ATIVO=true`. |
| `SATURDAY_GRANATECH_ATIVO` | `false` | Liga o cliente da Granatech no worker. O webhook fica sempre no ar. |
| `SATURDAY_GRANATECH_PROPOSTA_ATIVA` | `false` | Libera a criação automática de proposta. |
| `SATURDAY_GRANATECH_TETO_LIBERADO` | `6999` | Maior liberado apresentado ou contratado. |
| `SATURDAY_GRANATECH_COTA_MENSAL` | `500` | Teto de consultas no mês (alerta a 80%). |
| `SATURDAY_GRANATECH_COTA_DIARIA` | `20` | Limite de consultas no dia. |
| `SATURDAY_GRANATECH_REAPROVEITAR_DIAS` | `30` | Janela para reaproveitar consulta do mesmo CPF. |
| `SATURDAY_GRANATECH_TIPO_EMPREGADOR` | `1` | `tipo_empregador` do corpo da proposta (pendente de confirmação). |

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

O `release` também grava `atendimento = ia` em `conversas`, que desde a Fase 3 é
quem decide se a IA responde (docs/decisoes/0003). O `status` do `GET` continua
sendo o do grafo: uma conversa assumida no painel aparece ali como estava no
último turno da IA.

### API do painel (`/admin/*`)

Autenticada por cookie de sessão (`saturday_sessao`, 8 h). Toda rota que não é
`GET` exige o header `X-CSRF-Token`, devolvido pelo login e por `GET /admin/eu`,
e grava `auditoria`. As conversas são identificadas pelo `id` interno (UUID),
nunca pelo `conversation_id`, que no WhatsApp carrega o telefone.

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/admin/login` | `{email, senha}`. 5 falhas bloqueiam por 15 min; a resposta de erro é sempre a mesma. |
| `POST` | `/admin/logout` | Apaga a sessão. |
| `GET` | `/admin/eu` | Usuário, perfil e token CSRF. |
| `GET` | `/admin/usuarios` | Destinos de transferência. |
| `GET` | `/admin/conversas?fila=ia\|handoff\|assumida\|minhas&busca=` | Inbox, com `nao_lida` e `janela_aberta`. |
| `GET` | `/admin/conversas/{id}` | Histórico com autor e status de entrega; marca como vista. |
| `POST` | `/admin/conversas/{id}/assumir` | Atendente assume da IA ou do handoff; o gestor toma de outro atendente. |
| `POST` | `/admin/conversas/{id}/devolver` | Devolve para a IA (só o dono, ou o gestor). |
| `POST` | `/admin/conversas/{id}/transferir` | `{usuario_id}`; só conversa assumida. |
| `POST` | `/admin/conversas/{id}/mensagens` | `{texto}` ou `{modelo}`; só o dono, só WhatsApp. Janela fechada aceita só modelo. |
| `GET` | `/admin/conversas/{id}/ficha` | Dados mascarados. |
| `POST` | `/admin/conversas/{id}/revelar` | `{campo: cpf\|telefone\|data_nascimento}`; grava `revelar:{campo}` na auditoria. |
| `GET` | `/admin/alertas` | Alertas abertos (`handoff`, `erro_interno`, `envio_falhou`, `sem_resposta`). |
| `POST` | `/admin/alertas/{id}/resolver` | Resolve e audita. |
| `GET` | `/admin/cota` | Consultas Granatech no dia e no mês contra os tetos. |
| `GET` | `/admin/midia/{mensagem_id}/{indice}` | Anexo da mensagem, servido pela API (sem URL pré-assinada). |
| `GET` | `/admin/eventos` | SSE: avisos `{tipo, conversa\|alerta}` com IDs, sem dado pessoal. |

O painel só envia os modelos de utilidade sem botão de link, e sem variáveis:
o repositório ainda não sabe quantos parâmetros cada modelo tem, e os links
`/l/{codigo}` chegam na Fase 6.

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
   em branco (até 5 partes, 0,9 s entre elas); fechada → modelo `atualizacao_pedido`
   (sem variáveis, um por conversa) e a resposta espera na fila até o cliente
   escrever de novo.

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

## Granatech

Arquivos em `bancos/granatech/` (cliente, normalização, teto e ordem de status),
`dados/cota.py`, `web/api/granatech.py` e `jobs/granatech.py`. Explicação completa
em [`docs/granatech.md`](../../docs/granatech.md).

- `POST /webhooks/granatech` aceita o token em `?t=`, `Authorization: Bearer` ou
  `x-webhook-token` (tempo constante), grava em `eventos_recebidos` com o hash do
  JSON canônico como id e responde 200. Sem token configurado, 503.
- O worker aplica o status na consulta ou proposta local, na ordem da jornada;
  o `SUCCESS` da consulta grava o detalhe e, desde a Fase 5, roda um turno de
  sistema na conversa (ramo CLT, ver [`docs/clt.md`](../../docs/clt.md)).

O simulador fica em `simuladores/granatech/`:

```bash
uv run --project simuladores uvicorn app:app --app-dir simuladores/granatech --port 8200
```
