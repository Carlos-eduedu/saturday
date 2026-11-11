# 0006 — BrasilAPI sem interface `FonteCadastral`

- **Data:** 2026-11-11
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, "Interfaces para o futuro" (`fontes/base.py`)

## Contexto

O `AGENTS.md` pede `fontes/base.py` com uma `FonteCadastral`
(`buscar_por_cpf`, `buscar_empresa_por_cnpj`). Na Fase 5 a única fonte é a
BrasilAPI, que só consulta empresa; a NovaVida, que buscaria por CPF, está fora
do escopo.

## Decisão

A Fase 5 cria só `fontes/brasilapi.py`, com o cache de 30 dias por CNPJ na
tabela `empresas_cnpj` (compartilhada entre API e worker). O `Protocol` será
extraído quando a segunda fonte entrar, pelo mesmo motivo da
[decisão 0004](0004-sem-interface-banco-com-um-banco-so.md).

## Alternativas descartadas

- **Criar a `FonteCadastral` agora.** Metade da interface (`buscar_por_cpf`)
  não teria implementação nenhuma.
- **Cache só em memória.** Cada processo teria o seu, e o cache se perderia a
  cada deploy.
