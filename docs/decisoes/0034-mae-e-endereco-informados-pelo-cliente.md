# 0034 — Mãe e endereço informados pelo cliente

- **Data:** 2026-11-19
- **Status:** aceita
- **Substitui em parte:** [0029](0029-dados-do-tomador-conferidos-antes-da-proposta.md)
  (mãe e endereço só da Granatech)

## Contexto

A decisão 0029 mandava para o atendente a conversa cuja consulta viesse sem o
nome da mãe ou sem o endereço, e também a do cliente que dissesse "não" ao dado
da Granatech. Em 2026-11-19 a Granatech respondeu que esses dados vêm na
maioria dos casos e que, se faltarem, o parceiro pode preenchê-los.

## Decisão

Escolhas do usuário no Inbox, em 2026-11-19:

- **Mãe ausente, ou o cliente diz que a da Granatech está errada:** o agente
  pede o nome completo (pelo menos nome e sobrenome, como o nome do cliente) e
  grava em maiúsculas.
- **Endereço ausente, ou o cliente diz que o da Granatech está errado:** o
  agente pede o CEP e busca rua, bairro, cidade e UF na BrasilAPI
  (`/api/cep/v1`, sem repetição e sem cache), mostra o endereço achado e pede
  confirmação. Depois pede o número ("sem número" vira `S/N`) e o complemento
  ("não" vira vazio). Se o cliente disser que o endereço achado está errado, o
  agente pede o CEP de novo.
- **CEP não encontrado, BrasilAPI fora do ar ou endereço sem rua:** o agente
  pede ao cliente, um por mensagem, os campos que faltaram (rua, bairro, cidade,
  UF com sigla válida).
- O que o cliente informa fica em `clt.dados` (`mae`, `endereco`) e vale sobre
  o da Granatech no `dados-tomador`. A conferência do SIM do resumo continua
  exigindo os três dados.
- O nascimento continua como na 0029.

## Consequências

- Some o handoff `dados_divergentes` por mãe ou endereço; ele continua para a
  consulta sem nenhum dado da pessoa e para o nascimento ausente nos dois
  lados.
- O registro da chamada à BrasilAPI guarda só a rota com o marcador
  (`/api/cep/v1/{cep}`), nunca o CEP.
- A ficha do painel não mostra mãe nem endereço (nem os da Granatech); não há o
  que marcar como "informado pelo cliente".
