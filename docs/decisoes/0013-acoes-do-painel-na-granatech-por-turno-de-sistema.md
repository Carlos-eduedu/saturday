# 0013 — Aba Granatech: ações do gestor por turno de sistema, sem balcão manual

- **Data:** 2026-11-12
- **Status:** aceita

## Contexto

A equipe quer uma aba do painel focada na Granatech, para acompanhar consultas
e propostas e agir sobre elas. O cliente `bancos/granatech/` já sabe abrir
consulta, simular, criar proposta, reconciliar, cancelar e corrigir a conta,
mas o painel só mostra a cota e três alertas.

Abrir consulta, simular e criar proposta dependem de um SIM explícito do
próprio cliente, conferido em código e com prova gravada (regras 3, 4 e 5 do
`AGENTS.md`). Uma ação que mude a proposta no banco por fora do grafo deixaria
`clt.etapa` desatualizada.

## Decisão

- A aba tem duas listas, **Consultas** e **Propostas**: filtro por status e
  período, busca por CPF completo, CPF mascarado (o "revelar" de sempre, com
  auditoria), detalhe com vínculos, simulação, linha do tempo do `historico` e
  link para a conversa. O cabeçalho mostra a cota do dia e do mês. Tudo se
  atualiza pelo SSE de `/admin/eventos`.
- Atendente e gestor veem a aba; **só o gestor age**, e toda ação grava
  `auditoria`.
- As ações são cinco: reconciliar proposta incerta, reenviar o link de
  biometria, cancelar proposta (confirmação com motivo obrigatório), corrigir a
  conta e atualizar o detalhe da consulta.
- **Sem "atualizar status"**: o campo de status do `GET /propostas/{id}` não
  está documentado (regra 12). `TODO(granatech): em que campo o GET
  /propostas/{id} devolve o status?` O status segue chegando só pelo webhook.
- **Reconciliar** refaz o passo do aceite, que nunca repete o POST (com
  proposta incerta, `criar_proposta` só procura na listagem). Achada, a
  jornada segue sozinha: dados do tomador, aviso ao cliente e a conversa volta
  à IA (devolução auditada). Não achada, continua em handoff.
- **Corrigir a conta** (só com `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO`):
  formulário com banco da lista `GET /bancos` (só `habilitado`), agência,
  conta, dígitos e tipo; a conversa segue em handoff até o gestor devolver. A
  auditoria guarda só o código do banco e os 2 últimos dígitos da conta.
- **Ação que muda a jornada é um turno de sistema** (`AgentService.continuar`)
  sob a trava da conversa: reconciliar, reenviar o link e atualizar o detalhe.
  O grafo atualiza a etapa e qualquer mensagem ao cliente sai pelo outbox.
  Cancelar e corrigir a conta só chamam a Granatech: a jornada muda quando o
  webhook chegar, pelo caminho de sempre. Item sem `conversa_id` fica só para
  leitura.
- Com a conversa em handoff ou assumida, as ações mudam o estado e geram alerta
  para o dono, sem falar com o cliente; só "reenviar o link" fala sempre (com a
  janela fechada, pelo modelo `assinatura_pronta`).
- O cancelamento não avisa o cliente no clique: o aviso sai quando chega o
  webhook `CANCELED`, pelo caminho que já existe.
- Tudo passa pela cota e pelo reaproveitamento de sempre, em todos os
  ambientes, respeitando as flags existentes; não há flag nova.

## Alternativas descartadas

- **Balcão manual** (consulta, simulação e proposta pelo painel, sem conversa).
  Não há SIM do próprio cliente conferido em código; quebraria a regra 3.
- **Abrir consulta, simular ou criar proposta pelo painel numa conversa.**
  Também exigem o SIM do cliente, que só vem pela conversa.
- **Ação chamando a Granatech direto**, deixando o webhook corrigir o grafo
  depois. A etapa ficaria mentindo até o evento chegar, e uma mensagem do
  cliente no meio correria contra a ação.
- **Botão "pedir ao gestor" para o atendente.** Fora do escopo agora.
