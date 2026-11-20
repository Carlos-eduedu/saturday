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
docker compose --profile postgres --profile s3 up --build
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
| `SATURDAY_ENVIRONMENT` | `dev` | `dev`, `homolog`, `prod` ou `pytest` (pytest desliga as validações obrigatórias). |
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
| `SATURDAY_S3_ENDPOINT` | vazio | Endpoint do S3. Com o profile `s3` do compose, `http://s3:9090`; vazio = S3 da AWS. |
| `SATURDAY_S3_BUCKET` | vazio | Bucket dos anexos. Obrigatório com Postgres. |
| `SATURDAY_S3_ACCESS_KEY`, `SATURDAY_S3_SECRET_KEY` | vazio | Credenciais do S3. |
| `SATURDAY_OUTBOX_MAX_TENTATIVAS` | `8` | Tentativas de entrega antes de desistir. |
| `SATURDAY_OUTBOX_BACKOFF_BASE_S` | `2.0` | Espera inicial do backoff (dobra a cada falha). |
| `SATURDAY_RETENCAO_EXTRATO_DIAS` | `30` | Dias de retenção do extrato; ao expirar, o extrato é apagado no próximo turno. |
| `SATURDAY_HANDOFF_AUTO_RELEASE_HORAS` | `0` | Horas para liberar automaticamente um handoff sem dono; `0` desliga. Conversa assumida nunca é liberada sozinha. A liberação resolve os alertas `handoff`, `erro_interno`, `atendente_desativado` e `sem_resposta` da conversa, sem usuário. |
| `SATURDAY_SESSAO_SEGREDO` | vazio | Assina o CSRF do painel. Obrigatória fora de `pytest`. |
| `SATURDAY_GRANATECH_BASE_URL` | api-dev | Base da API da Granatech; em dev, o simulador (`http://granatech:8200`). |
| `SATURDAY_GRANATECH_CHAVE_API` | vazio | Chave do login. Obrigatória com `GRANATECH_ATIVO=true`. |
| `SATURDAY_GRANATECH_WEBHOOK_TOKEN` | vazio | Token do webhook. Sem ele, `/webhooks/granatech` responde 503; obrigatória em `homolog` e `prod` e com `GRANATECH_ATIVO=true`. |
| `SATURDAY_GRANATECH_ATIVO` | `false` | Liga o cliente da Granatech no worker. O webhook fica sempre no ar. |
| `SATURDAY_GRANATECH_SIMULADOR_URL` | vazio | Simulador da Granatech só para conversas de membro testador (decisão 0020); vazio desliga. Não vale em `prod`. |
| `SATURDAY_GRANATECH_SIMULADOR_CHAVE`, `SATURDAY_GRANATECH_SIMULADOR_WEBHOOK_TOKEN` | vazio | Chave e token próprios do simulador. Obrigatórios com `GRANATECH_SIMULADOR_URL`. |
| `SATURDAY_GRANATECH_PROPOSTA_ATIVA` | `false` | Libera a criação automática de proposta. Exige `DOMINIO_PUBLICO`. |
| `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO` | `false` | Liga a correção de conta (PATCH) depois de falha de pagamento. |
| `SATURDAY_DOMINIO_PUBLICO` | vazio | Domínio dos links curtos da biometria (`https://{dominio}/l/{codigo}`), com ou sem `https://`. Obrigatória com `GRANATECH_PROPOSTA_ATIVA=true`. |
| `SATURDAY_GRANATECH_TETO_LIBERADO` | `6999` | Maior liberado apresentado ou contratado. |
| `SATURDAY_GRANATECH_COTA_MENSAL` | `500` | Teto de consultas no mês (alerta a 80%). |
| `SATURDAY_GRANATECH_COTA_DIARIA` | `20` | Limite de consultas no dia. |
| `SATURDAY_GRANATECH_REAPROVEITAR_DIAS` | `30` | Janela para reaproveitar consulta do mesmo CPF. |
| `SATURDAY_EVOLUTION_ATIVO` | `false` | Liga o canal Evolution (ver [`docs/evolution.md`](../../docs/evolution.md)). |
| `SATURDAY_EVOLUTION_URL` | `http://evolution:8080` | Endereço da Evolution API; em dev, o simulador. |
| `SATURDAY_EVOLUTION_API_KEY`, `SATURDAY_EVOLUTION_WEBHOOK_TOKEN` | vazio | Chave da Evolution e token do webhook. Obrigatórias com `EVOLUTION_ATIVO=true`. |
| `SATURDAY_EVOLUTION_WEBHOOK_URL` | `http://api:8000/webhooks/evolution` | Para onde a Evolution manda os eventos. |
| `SATURDAY_C6_ATIVO` | `false` | Liga a API do C6 no ramo INSS (decisão 0026, ver [`docs/c6.md`](../../docs/c6.md)). |
| `SATURDAY_C6_BASE_URL`, `SATURDAY_C6_USUARIO`, `SATURDAY_C6_SENHA`, `SATURDAY_C6_CODIGO_PROMOTORA` | vazio | Endereço, credencial e código de promotora. Obrigatórias com `C6_ATIVO=true`; em dev, a `BASE_URL` aponta para o simulador. |
| `SATURDAY_ICRED_ATIVO` | `false` | Liga a consulta ao iCred no ramo INSS (decisão 0027, ver [`docs/icred.md`](../../docs/icred.md)). |
| `SATURDAY_ICRED_BASE_URL`, `SATURDAY_ICRED_CHAVE_API`, `SATURDAY_ICRED_WEBHOOK_SEGREDO` | vazio | Endereço e chave do motor e segredo do webhook. Obrigatórias com `ICRED_ATIVO=true`; em dev, a `BASE_URL` aponta para o simulador. |
| `SATURDAY_ICRED_ESPERA_MIN` | `5` | Minutos sem resposta até a conversa seguir sem o iCred e abrir alerta. |

A lista completa, com as variáveis do WhatsApp, da transcrição, da fila de
eventos e do compose, está no `.env.example` da raiz.

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
`dados_cliente_nao_informados`, `idade_fora_regra`,
`especie_nao_atendida`, `extrato_ilegivel` ou `erro_interno`.
Conversa anterior a 07/11/2026 ainda pode trazer `idade_prazo_96`, que nenhuma
regra emite mais.

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
quem decide se a IA responde (docs/decisoes/0003), e resolve os alertas `handoff`,
`erro_interno`, `atendente_desativado` e `sem_resposta` da conversa, sem usuário. O `status` do `GET` continua
sendo o do grafo: uma conversa assumida no painel aparece ali como estava no
último turno da IA.

### API do painel (`/admin/*`)

Autenticada por cookie de sessão (`saturday_sessao`, 8 h). Toda rota que não é
`GET` exige o header `X-CSRF-Token`, devolvido pelo login e por `GET /admin/eu`,
e grava `auditoria`. Com a troca de senha obrigatória pendente (decisão 0030),
todas respondem 403 "troque a senha para continuar", menos `GET /admin/eu`,
`POST /admin/eu/senha` e `POST /admin/logout`. As conversas são identificadas pelo `id` interno (UUID),
nunca pelo `conversation_id`, que no WhatsApp carrega o telefone.

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/admin/login` | `{email, senha}`. 5 falhas bloqueiam por 15 min; a resposta de erro é sempre a mesma. |
| `POST` | `/admin/logout` | Apaga a sessão. |
| `GET` | `/admin/eu` | Usuário, perfil, token CSRF e `trocar_senha` (troca obrigatória pendente). |
| `POST` | `/admin/eu/senha` | `{atual, nova}`: a pessoa troca a própria senha (12 ou mais, diferente da atual). Encerra as outras sessões dela e desliga a troca obrigatória. Senha atual errada responde 422 e conta para o bloqueio do login. |
| `GET` | `/admin/usuarios` | Destinos de transferência, com o `estado` de cada pessoa (`disponivel`, `ausente` ou `fora`). |
| `GET` | `/admin/membros` | A equipe, para todos (decisão 0023). Os campos dependem de quem pede (`nivel`: `colega`, `proprio` ou `gestor`); desativados e `trocar_senha` (troca obrigatória pendente) só para o gestor. |
| `GET` | `/admin/membros/{id}` | Um membro. Para a própria pessoa e para o gestor traz também `atividade` (7 dias) e `acoes` (as 10 últimas, sem o detalhe da auditoria). |
| `PATCH` | `/admin/eu/disponibilidade` | `{disponivel}`: a própria pessoa marca disponível ou ausente. Informa quem transfere; não bloqueia. |
| `GET` | `/admin/conversas?fila=ia\|handoff\|assumida\|minhas&busca=` | Inbox, com `nao_lida` e o que o canal permite agora: `envia`, `janela` (`aberta`, `fechada` ou `null` no canal sem janela) e `modelos` (as 200 mais recentes). |
| `GET` | `/admin/conversas/contagens` | Quantas conversas há em cada fila (`todas`, `ia`, `handoff`, `assumida`, `minhas`) e quantas pedem atenção (`atencao`), em toda a base. |
| `GET` | `/admin/conversas/{id}` | Histórico com autor e status de entrega; marca como vista. |
| `POST` | `/admin/conversas/{id}/assumir` | Atendente assume da IA ou do handoff; o gestor toma de outro atendente. Resolve os alertas `handoff`, `erro_interno` e `atendente_desativado` da conversa (docs/decisoes/0018 e 0021). |
| `POST` | `/admin/conversas/{id}/desfazer` | Desfaz o último assumir ou devolver de quem pede, por até 15 s e enquanto nada mais mexeu no atendimento; a conversa volta ao estado de antes (IA, handoff ou o dono anterior), com os alertas que a ação resolveu reabertos. |
| `POST` | `/admin/conversas/{id}/devolver` | Devolve para a IA (só o dono, ou o gestor). Resolve os alertas `handoff`, `erro_interno`, `atendente_desativado` e `sem_resposta` da conversa. |
| `POST` | `/admin/conversas/{id}/transferir` | `{usuario_id}`; só conversa assumida. |
| `POST` | `/admin/conversas/{id}/mensagens` | `{texto}` ou `{modelo}`; só o dono, só WhatsApp. Janela fechada aceita só modelo. |
| `GET` | `/admin/conversas/{id}/ficha` | Dados mascarados, mais a oferta do CLT (só valores), a última oferta mostrada ao cliente em qualquer ramo (`oferta_vigente`: `ramo`, `situacao` `vigente` ou `recusada` e os `valores` em reais que a fala cita), a oferta que o estado guarda de cada ramo (`ofertas`, com a mesma `situacao`, nula na oferta anterior; a mensagem da conversa leva `ramo_da_oferta` quando é a fala fixa de uma oferta), a faixa da portabilidade enquanto ela for a vigente (`portabilidade_oferta`), a última proposta na Granatech com `difere_da_oferta` e as provas de consentimento (sem o CPF). |
| `POST` | `/admin/conversas/{id}/revelar` | `{campo: cpf\|telefone\|data_nascimento}`; grava `revelar:{campo}` na auditoria. |
| `GET` | `/admin/alertas` | Alertas abertos (`handoff`, `erro_interno`, `atendente_desativado`, `envio_falhou`, `sem_resposta`, `evento_com_humano`, `cota_80`, `consulta_parada`, `granatech_evento`, `icred_consulta_parada`, `instancia_desconectada`, `instancia_numero_trocado`, `integracao_webhook_falhou`). |
| `POST` | `/admin/alertas/{id}/resolver` | Resolve e audita. |
| `GET` | `/admin/cota` | Consultas Granatech no dia e no mês contra os tetos. |
| `GET` | `/admin/funil` | Só gestor. `?periodo=hoje\|7d\|30d\|mes` (padrão `mes`): por produto, as conversas iniciadas no período que chegaram a cada etapa (`etapas`, e em `produtos[].celulas` a contagem e a `taxa` sobre a etapa anterior; célula nula é etapa que o produto não tem), mais `iniciadas` e `sem_publico`. Fontes e regra de período na decisão 0031. |
| `GET` | `/admin/midia/{mensagem_id}/{indice}` | Anexo da mensagem, servido pela API (sem URL pré-assinada). Imagem (JPG, PNG, WebP, GIF), áudio, vídeo e PDF abrem no navegador; qualquer outro tipo sai como download (`Content-Disposition: attachment`), porque o tipo é o que o cliente declarou. |
| `GET` | `/admin/eventos` | SSE: avisos `{tipo, conversa\|alerta}` com IDs, sem dado pessoal. |

O painel só envia os modelos de utilidade sem botão de link, e sem variáveis:
o repositório ainda não sabe quantos parâmetros cada modelo tem, e os modelos
com botão de link levam o código de um link curto (`/l/{codigo}`), que o
compositor do painel não gera.

### Integração (`/integracao/*`)

Proxy da Granatech para o APP MEX (decisão 0035), autenticado por
`Authorization: Bearer` com um token gerado na página Integrações do painel
(`/admin/gestao/integracoes`, só gestor). Rotas, escopos e respostas em
`docs/granatech.md`, "Integração (APP MEX)".

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

A tela Canais do painel lê o número exibido e a qualidade de cada número por
`GET /{phone_number_id}` (fora da especificação: decisão 0032 e
[`docs/meta.md`](../../docs/meta.md)), com a leitura guardada 60 s em memória.

O simulador da Meta fica em `simuladores/meta/` e cobre envio, download de mídia,
leitura do número (`POST /admin/numero` troca a qualidade) e injeção de mensagem
assinada:

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

## iCred

Arquivos em `bancos/icred/` (cliente e normalização), `agent/icred/` (regras,
textos e nós), `web/api/icred.py` e `jobs/icred.py`. O que existe e o que o
motor faz estão em [`docs/icred.md`](../../docs/icred.md); as decisões, na 0027.

- Só com `SATURDAY_ICRED_ATIVO=true`. Sem ela, o ramo INSS é o de antes.
- `POST /webhooks/icred` confere a assinatura HMAC em tempo constante
  (`X-Icred-Assinatura` sobre `<timestamp>.<corpo>`), recusa timestamp com mais
  de 5 minutos, grava em `eventos_recebidos` com o `X-Icred-Id` e responde 200.
  Sem segredo configurado, 503.
- O worker aplica `consulta.concluida` na consulta local e roda um turno de
  sistema na conversa. Consulta sem resposta em `SATURDAY_ICRED_ESPERA_MIN` é
  lida por id; continuando parada, a conversa segue sem o iCred e abre o alerta
  `icred_consulta_parada`.

O simulador fica em `simuladores/icred/`:

```bash
uv run --project simuladores uvicorn app:app --app-dir simuladores/icred --port 8400
```
