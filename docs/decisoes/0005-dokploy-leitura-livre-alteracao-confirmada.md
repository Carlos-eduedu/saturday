# 0005 — Dokploy: leitura livre, alteração só com confirmação

- **Data:** 2026-11-11
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, "Forma de trabalho" ("Nunca rode comandos que falem
  com produção (Granatech, Meta, Dokploy)")

## Contexto

O único painel Dokploy da MEX é de produção e hospeda o Saturday e outros
projetos. O usuário quer que o agente o ajude a criar e gerir projetos e
ambientes pelo MCP oficial (`@dokploy/mcp`), o que a regra original impedia.

## Decisão

- Leitura livre: listar e consultar projetos, ambientes, serviços, deploys e logs.
- Alteração (criar, editar, deploy, parar, apagar) só depois de confirmação
  explícita do usuário para aquela ação, com o alvo identificado por nome e ID.
- O agente nunca lê nem exibe o token do painel nem os valores de variáveis de
  ambiente dos serviços; ao relatar respostas da API, mostra só nomes e IDs.
- Granatech e Meta de produção continuam proibidas.

## Alternativas descartadas

- **Manter a proibição.** Obriga o usuário a fazer à mão tudo no painel.
- **Liberar tudo.** Um deploy ou uma exclusão errada derruba serviços de
  produção que não são do Saturday.
