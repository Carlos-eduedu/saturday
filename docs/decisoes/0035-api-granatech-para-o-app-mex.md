# 0035 — Saturday como proxy da Granatech para o APP MEX

- **Data:** 2026-11-20
- **Status:** proposta
- **Emenda:** regra 1 do `AGENTS.md`
- **Estende:** [0013](0013-acoes-do-painel-na-granatech-por-turno-de-sistema.md), [0025](0025-uma-acao-do-gestor-por-vez.md)
- **Ver também:** [0036](0036-consentimento-e-triagem-pela-integracao.md)

## Contexto

O APP MEX, sistema da MEX, quer abrir consultas, simular, criar e acompanhar
propostas na Granatech. As credenciais, a cota (dividida com o agente) e a URL
do webhook da Granatech estão no Saturday; ele fica no meio.

A regra 1 proibia o Saturday de chamar qualquer sistema da MEX. Avisar o APP
MEX dos status exige chamá-lo.

## Decisão

- **Proxy transparente.** Em `/integracao/granatech/api-consignado/v1/...` o
  Saturday repassa à Granatech as mesmas rotas e os mesmos corpos dela, trocando
  o token da integração pelo login da MEX. Só uma lista fechada, a que o
  `bancos/granatech/cliente.py` já usa: `consulta-saldo` (abrir, listar por
  usuário, detalhe), `termo-consentimento`, `simulacao/{id_produto}`, `bancos`,
  `propostas` (criar, `lista`, detalhe, `dados-tomador`, `cancelar`,
  `dados-bancarios`). Outra rota: 404 (regra 12).
- **CPF mascarado, único desvio do cru.** Na resposta do proxy, o valor de toda
  chave com "cpf" no nome e de `document`/`documento` sai mascarado
  (`***.***.***-25`). O CPF inteiro só sai pelo revelar, com o escopo
  `revelar` e auditado (regra 9); sem isso, o escopo `leitura` já o mostraria.
- **O que o proxy barra**, antes ou depois de repassar:
  - token sem o escopo da rota (403);
  - consulta que fura a cota diária ou mensal; CPF com consulta recente devolve
    a mesma, sem abrir outra (regra 5);
  - simulação ou proposta com liberado acima do teto (422, regra 6);
  - proposta sem `Idempotency-Key` ou de simulação que o Saturday não repassou;
    a intenção é gravada antes, não há retry, e o resultado incerto vira 202
    "incerta" (regra 4);
  - escrita em consulta ou proposta que nasceu numa conversa do agente (409:
    a etapa da conversa ficaria mentindo, como na 0013).
- **Registro local.** Consultas e propostas da integração vão às tabelas de
  sempre, sem `conversa_id` e com o id do token: o painel as mostra e o webhook
  sabe a quem repassar.
- **Tokens no painel.** Página **Integrações**, só do gestor: gera (mostrado uma
  vez, só o hash no banco), dá nome e escopos (`leitura`, `revelar`, `acoes`,
  `operacoes`, `homologacao`), revoga. Criação e revogação na auditoria; ações
  da integração com `usuario_id` nulo e `detalhe.origem = "integracao"`.
- **Webhook de saída.** Cada token tem um endpoint. Evento da Granatech de item
  da integração é tratado como hoje e repassado cru, assinado com HMAC-SHA256
  por um segredo do endpoint (mostrado uma vez), pelo outbox (canal `webhook`,
  reagendamento da 0001). Endpoint fora do ar não trava nada.
- **Rotas próprias** em `/integracao/`: revelar CPF, cota do dia e do mês,
  homologação (0014).
- **Regra 1 emendada:** o Saturday pode avisar por webhook o endpoint de uma
  integração cadastrada no painel; não lê nada do sistema avisado nem depende da
  resposta.

## Consequências

- Uma consulta do APP MEX gasta a mesma cota do agente.
- A lista de rotas é contrato com o APP MEX: rota nova da Granatech só passa
  depois de entrar na lista.
- O painel passa a mostrar itens sem conversa que não são homologação.

## Alternativas descartadas

- **JSON do Saturday** (o do painel) em vez do formato da Granatech. Mais
  código e um contrato nosso para manter.
- **Repassar qualquer rota.** Furaria cota e teto e deixaria passar rota que não
  conhecemos.
- **Só de entrada, sem webhook.** O APP MEX teria de consultar o status em laço.
- **Token na variável de ambiente.** Não dá para revogar um sem afetar outro nem
  ver o último uso.
- **Usuário de serviço em `usuarios_painel`.** Apareceria como pessoa no painel.
