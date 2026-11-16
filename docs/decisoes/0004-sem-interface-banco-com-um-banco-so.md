# 0004 — Sem interface `Banco` enquanto houver um banco só

- **Data:** 2026-11-11
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, "Interfaces para o futuro" (`bancos/base.py`)

## Contexto

O `AGENTS.md` pede `bancos/base.py` com um `Banco` (`elegivel`, `consultar`,
`simular`, `criar_proposta`, `status`, `processar_evento`). Na Fase 4 a
Granatech é o único banco, e a forma desses métodos depende de contratos ainda
pendentes (resposta da proposta, seguro, listagem por CPF).

## Decisão

A Fase 4 cria só o cliente da Granatech em `bancos/granatech/`. O `Protocol`
será extraído quando o segundo banco entrar, a partir do que os dois tiverem em
comum.

**Nota de 2026-11-16 (decisão 0027).** O iCred entrou como `bancos/icred/`, ainda
sem `Protocol`: ele vive no ramo INSS e a Granatech no CLT, e as duas jornadas
não se cruzam. A interface fica para quando dois bancos disputarem o mesmo
ponto do grafo (a API do C6, decisão 0026).

## Alternativas descartadas

- **Criar o `Protocol` completo agora.** Uma interface com uma implementação só
  não é validada por ninguém e tende a copiar as particularidades da Granatech.
