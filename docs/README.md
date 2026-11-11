# Documentação do Saturday

Índice do que está documentado hoje. O contrato de trabalho continua sendo o
[`AGENTS.md`](../AGENTS.md); aqui ficam explicações que não cabem nele.

## Comece por aqui

- [`../README.md`](../README.md) — como rodar local e com Docker, estrutura do monorepo.
- [`../apps/core/README.md`](../apps/core/README.md) — contrato da API (`/chat`, conversas,
  webhook do WhatsApp) e variáveis de ambiente.
- [`../AGENTS.md`](../AGENTS.md) — regras inegociáveis, arquitetura alvo e fases.
- [`granatech.md`](granatech.md) — cliente, cota, webhook e simulador da Granatech.

## Decisões

Registro do **porquê** das escolhas que não são óbvias pelo código. Cada arquivo é
imutável: quando uma decisão muda, entra um registro novo que a substitui.

- [`decisoes/0001-outbox-dono-do-reagendamento.md`](decisoes/0001-outbox-dono-do-reagendamento.md)
  — o canal só classifica; quem espera e desiste é o outbox.
- [`decisoes/0002-workspace-uv-unico.md`](decisoes/0002-workspace-uv-unico.md)
  — um `uv.lock` e um `.venv` na raiz do monorepo.
- [`decisoes/0003-estado-de-atendimento-na-tabela-conversas.md`](decisoes/0003-estado-de-atendimento-na-tabela-conversas.md)
  — quem responde a conversa mora em `conversas`, não no checkpoint.
- [`decisoes/0004-sem-interface-banco-com-um-banco-so.md`](decisoes/0004-sem-interface-banco-com-um-banco-so.md)
  — o `Protocol` de banco espera o segundo banco.

## Estado por fase

| Fase | Entrega | Documentação |
| --- | --- | --- |
| 0 | monorepo, compose, CI | `README.md` |
| 1 | Postgres, outbox, worker, S3, travas | `apps/core/README.md` |
| 2 | canal WhatsApp e simulador da Meta | `apps/core/README.md`, ADR 0001 |
| 3 | painel e API admin | `apps/core/README.md`, ADR 0003 |
| 4 | cliente e simulador da Granatech | `granatech.md`, ADR 0004 |
| 5 a 7 | pendentes | — |
