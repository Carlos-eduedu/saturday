# 0008 — Dados da proposta antes do SIM do aceite

- **Data:** 2026-11-11
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, "Especificação: jornada CLT" (`aceite` → `dados_proposta`)

## Contexto

O `AGENTS.md` ordena `oferta` → `aceite` (resumo e SIM) → `dados_proposta`
(mãe, endereço, estado civil e conta) → `proposta`. Nessa ordem, o SIM gravado
como consentimento do tipo `proposta` não cobre a conta onde o dinheiro cai, que
só é informada depois.

## Decisão

A ordem passa a ser `oferta` → `dados_proposta` → `aceite` → `proposta`. Quando
o cliente quer seguir com a oferta, o agente confirma o nome da mãe e o
endereço, e pede o estado civil e a conta. O resumo fechado, com os valores e a
conta mascarada, leva o SIM. Esse SIM é a prova do tipo `proposta` e dispara a
criação da proposta. Nenhuma regra muda; só a ordem.

## Por quê

- O SIM autoriza exatamente o que vai para o banco: valores e conta.
- Um erro na conta é corrigido antes da proposta existir, não depois.

## Alternativas descartadas

- **Manter a ordem do contrato.** A prova de consentimento ficaria sem a conta,
  e uma conta errada só apareceria depois da proposta criada.
