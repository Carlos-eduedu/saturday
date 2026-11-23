# 0038 — Sentry para erros do backend

- **Data:** 2026-11-23
- **Status:** aceita

## Contexto

Os erros do Saturday só aparecem no log JSON dos containers. Quase nenhuma
exceção sobe solta: cerca de 30 pontos (worker, outbox, turno, clientes dos
bancos) pegam o erro, registram com `logger.exception` ou `logger.error` e
seguem. Ninguém é avisado; é preciso abrir o log no Dokploy para saber que algo
quebrou. A regra 1 lista os parceiros externos do negócio e não cobre um
serviço de observabilidade, que também recebe dados que saem do serviço.

## Decisão

- **Sentry SaaS, só para erros do backend** (API `saturday` e
  `saturday-worker`). O painel fica de fora por enquanto. Sentry não é parceiro
  de negócio: o Saturday só envia eventos, não lê nada dele nem depende da
  resposta.
- **Liga por variável:** `SATURDAY_SENTRY_DSN`, opcional. Vazia, o SDK não
  inicia; com `environment == "pytest"`, nunca inicia. A tag `environment` é o
  `SATURDAY_ENVIRONMENT`. Sem `release` por enquanto: a imagem não carrega o
  SHA do commit.
- **Log de erro vira evento:** a integração de logging transforma
  `logger.error`/`logger.exception` em evento; breadcrumbs só de WARNING para
  cima. O ruído esperado (envio permanente para número inválido) se silencia no
  próprio Sentry, não por lista no código.
- **O que não sai (regra 9):** no `sentry-sdk` 3, pelo `data_collection`:
  usuário, cookies, headers, corpos, query de URL, entradas e saídas de IA,
  consultas ao banco e variáveis dos frames (que carregam CPF, telefone e texto
  da mensagem). As integrações automáticas ficam desligadas (IA, httpx, banco,
  FastAPI): só a de logging entra. O 500 da API chega pelo log de erro: o
  `erro_nao_tratado` (rota e tipo) e o do uvicorn (com o stack trace), sem a
  requisição. Sem tracing, profiling nem logs. O `before_send` e
  o `before_breadcrumb` passam todo texto do evento por `mascarar_texto`
  (`privacidade.py`) e cortam a query das URLs, como no access log (a consulta
  da Granatech leva CPF, nome e telefone na URL).
- **Projeto:** `saturday`, na organização `mex-promotora` do Sentry, separado
  do `mex-crm`. O Saturday não lê nada do outro projeto (regra 1). Região dos
  EUA (a da conta). Alerta por e-mail para issue nova em `prod`.

## Consequências

- Erro em produção avisa por e-mail sem ninguém olhar o log.
- Os eventos saem do Brasil já mascarados; o que a máscara não reconhece
  (nome, endereço em texto livre numa mensagem de erro) pode passar. Por isso
  variáveis locais e corpos de requisição nunca vão.
- Um `logger.error` novo vira alerta. Quem escreve um erro esperado usa
  `warning`.
- Ligar tracing ou o painel depois pede rever esta decisão.
