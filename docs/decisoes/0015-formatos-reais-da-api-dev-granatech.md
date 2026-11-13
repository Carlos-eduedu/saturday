# 0015 — Formatos reais da api-dev da Granatech no lugar dos documentados

- **Data:** 2026-11-13
- **Status:** aceita (aguardando confirmação da Granatech)

## Contexto

As rodadas 6 a 13 da homologação (aba Granatech do painel, contra a api-dev)
mostraram que a API real difere da especificação do `AGENTS.md` e dos PDFs da
Granatech em cinco pontos. Com o formato documentado, a fase 2 parava na
primeira contratação e a jornada CLT do agente falharia em todas as propostas
com seguro. As perguntas foram enviadas no grupo da Granatech em 2026-11-13,
sem resposta até aqui.

## Decisão

O Saturday segue o que a api-dev respondeu, mantendo o formato documentado onde
ele não conflita:

- **`informacaoDeSeguros.id_externo`** vai como **número**: o
  `id_cobertura_seguro` do produto (o `id_produto_seguro` da simulação, 1214 na
  dev). O `AGENTS.md` manda "`id_externo` como texto", com o valor
  `"SM-…"` da simulação; a api-dev recusa (400, `id_externo must be a number`),
  e sem o bloco recusa todo produto com seguro (`é obrigatório informar as
  informações de seguro`). Com a cobertura, aceitou nas rodadas 10, 11 e 13.
  Sem cobertura numérica no produto, sobra o `"SM-…"`.
- **Resposta do `POST /propostas`:** o 201 traz só o id, como texto JSON;
  aceitamos também `id`, `id_proposta` ou `data.id` num objeto.
- **Webhook de proposta:** chega como `{tipo: "PROPOSTA", status, id_proposta,
  cpf}`, com o nome da notificação (`AGUARDANDO_CONFIRMACAO`) em `status` e sem
  `tipo_notificacao`. Lemos os dois formatos; o status sai da tabela de
  `docs/granatech-homologacao/webhook-propostas.md`.
- **Webhook de consulta:** status em português; `AGUARDANDO_AUTORIZACAO_DO_CLIENTE`
  e `CONCLUIDO` viram `AWAITING_CLIENT_AUTHORIZATION` e `SUCCESS`. Outro nome
  continua virando alerta.
- **`dados-tomador.data_nascimento`:** vai como `AAAA-MM-DDT00:00:00.000Z`, o
  formato do exemplo da collection de contratação; só a data dá 400 (`must be
  a Date instance`).

## Consequências

- Cada ponto tem `TODO(granatech)` no código e está em `docs/granatech.md`.
  Se a resposta da Granatech mudar algum, a troca é local
  (`bancos/granatech/normalizacao.py` e `status.py`).
- Os CPFs gerados pela api-dev vêm sem nascimento, mãe e endereço; a
  homologação completa com os dados de teste da collection. A jornada do agente
  ainda não pede ao cliente o que a Granatech não devolver: o `dados-tomador`
  falha nesse caso (pendência registrada em `docs/granatech.md`).
