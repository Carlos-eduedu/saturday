# 0003 — O estado de atendimento mora na tabela `conversas`

- **Data:** 2026-11-11
- **Status:** aceita
- **Substitui:** o handoff guardado só no checkpoint do grafo (Fases 1 e 2)

## Contexto

Até a Fase 2, o handoff vivia só no checkpoint do LangGraph (`status`,
`handoff_reason`, `handoff_em`). O painel da Fase 3 precisa listar e filtrar
conversas por fila (com a IA, handoff, assumida, por atendente), e o checkpoint
não é consultável por SQL. Além disso, a Fase 3 introduz um estado novo — a
conversa **assumida** por um atendente — que não é decisão do grafo, e sim de
uma pessoa.

## Decisão

- `conversas` ganha o estado de atendimento (`ia`, `handoff`, `assumida`), o
  atendente dono e o horário da última mudança. Essa é a fonte da verdade.
- O `AgentService` lê esse estado, sob a trava da conversa, antes de rodar o
  turno: em `handoff` ou `assumida`, não roda o grafo e não responde.
- O grafo continua decidindo **entrar** em handoff; o serviço grava a
  transição em `conversas` na mesma transação do turno. `handoff_reason`
  continua no checkpoint, para o grafo.
- A liberação automática (`handoff_auto_release_horas`) vale só para `handoff`.
  Conversa `assumida` só volta para a IA quando alguém a devolve.

## Alternativas descartadas

- **Manter no checkpoint e espelhar em `conversas`.** Duas fontes que podem
  divergir; o painel mostraria uma fila e o worker obedeceria a outra.
- **Tabela separada de atribuições.** Histórico de donos já fica na
  `auditoria`; uma tabela própria só duplicaria.

## Consequências

- Migração nova e ajuste do `POST /conversations/{id}/release` para escrever em
  `conversas`. A rota mantém o nome `/release` para não quebrar o contrato
  HTTP atual; o painel e a API admin nova usam "devolver", como no glossário.
- Conversas do `POST /chat` sem Postgres (ambiente `pytest`) não têm onde
  guardar o estado; os testes do painel exigem o banco.
