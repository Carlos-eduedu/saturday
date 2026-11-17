# Documentação do Saturday

Índice do que está documentado hoje. O contrato de trabalho continua sendo o
[`AGENTS.md`](../AGENTS.md); aqui ficam explicações que não cabem nele.

## Comece por aqui

- [`../README.md`](../README.md) — como rodar local e com Docker, estrutura do monorepo.
- [`../apps/core/README.md`](../apps/core/README.md) — contrato da API (`/chat`, conversas,
  webhook do WhatsApp) e variáveis de ambiente.
- [`../AGENTS.md`](../AGENTS.md) — regras inegociáveis, ponteiros da especificação e comandos.
- [`granatech.md`](granatech.md) — cliente, cota, webhook e simulador da Granatech.
- [`clt.md`](clt.md) — ramo CLT: etapas, proposta, pós-venda, turnos de sistema e recontato.
- [`c6.md`](c6.md) — API do C6: contrato novo INSS, consentimento, cliente, simulador e pendências.
- [`icred.md`](icred.md) — iCred pelo motor de consultas: como está hoje e a pesquisa da especificação.
- [`evolution.md`](evolution.md) — canal Evolution: instâncias, webhook e simulador.
- [`deploy.md`](deploy.md) — ambientes, ambiente do zero, backup e restauração no Dokploy.
- [`granatech-homologacao/`](granatech-homologacao/README.md) — material da homologação com a Granatech.

## Decisões

Registro do **porquê** das escolhas que não são óbvias pelo código. Cada arquivo é
imutável: quando uma decisão muda, entra um registro novo que a substitui.

Ficam em [`decisoes/`](decisoes/); o nome de cada arquivo diz o tema.

## Estado por fase

Ver [`estado.md`](estado.md).
