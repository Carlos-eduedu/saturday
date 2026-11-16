# 0021 — `atendente_desativado` entra no ciclo do alerta de handoff

- **Data:** 2026-11-16
- **Status:** aceita
- **Estende:** 0018

## Contexto

Desativar um atendente devolve à fila as conversas que ele tinha assumido: cada
uma vai para `handoff` com o alerta `atendente_desativado`. A decisão 0018 lista
os alertas que assumir e devolver resolvem e não cita este. Na prática ele
ficava aberto depois de alguém pegar a conversa, até um clique em "resolver" na
aba Alertas, e o card da conversa mostrava o motivo de um handoff antigo, ou
nenhum.

A regra da 0018 também estava repetida em cada lugar que muda o estado de
atendimento (sete chamadas em quatro arquivos), e foi assim que este tipo ficou
de fora.

## Decisão

- `atendente_desativado` é um alerta de handoff, como `handoff` e
  `erro_interno`:
  - **assumir** e **devolver** o resolvem, em nome de quem agiu;
  - a **liberação automática** do handoff o resolve, sem usuário;
  - **desfazer** o reabre, pelos ids da auditoria, como os outros;
  - o card e o cabeçalho da conversa mostram "Atendente desativado" como motivo.
- Desativar não abre um segundo `atendente_desativado` se já houver um aberto
  na conversa.
- O estado de atendimento só muda por `dados/atendimento.py`. Cada verbo
  (`assumir`, `devolver`, `entrar_em_handoff`, `transferir`, `restaurar`) grava
  o estado, avisa o painel e abre ou resolve os alertas dele. Regra de dono,
  auditoria e desfazer continuam em `painel/acoes.py`.

## Alternativas descartadas

- **Deixar o alerta aberto de propósito.** Ele diz por que a conversa voltou à
  fila; depois que alguém a assume, não há mais nada a fazer com ele.
- **Migrar os alertas já abertos.** São poucos e se resolvem no próximo assumir
  ou devolver da conversa.

## Consequências

- Tipo novo de alerta que ponha a conversa em handoff entra em
  `TIPOS_DE_HANDOFF` e passa a valer para assumir, devolver, liberação e card
  de uma vez.
- Sem migração de banco.
