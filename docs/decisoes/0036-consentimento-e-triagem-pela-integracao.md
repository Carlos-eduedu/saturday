# 0036 — Consentimento e triagem pela integração são do APP MEX

- **Data:** 2026-11-20
- **Status:** proposta
- **Emenda:** regras 3 e 5 do `AGENTS.md`
- **Ver também:** [0035](0035-api-granatech-para-o-app-mex.md)

## Contexto

Pelo proxy da 0035, o APP MEX abre consulta e cria proposta sem conversa com o
agente. O Saturday não fala com o cliente e não tem como ouvir o SIM dele nem
fazer as perguntas da triagem.

## Decisão

- Pela integração, **triagem e consentimento são do APP MEX**, que os colhe,
  guarda e responde por eles. O Saturday não confere nem grava a prova.
- A **cota** continua conferida pelo Saturday (0035).
- Regra 3 emendada: a exceção vale só para a integração; no agente, o SIM do
  cliente segue conferido em código e com prova gravada, e "nunca simule aceite
  com dados de aparelho inventados" vale só para o agente.
- Regra 5 emendada: pela integração, triagem e consentimento são do APP MEX.

## Consequências

- O que o APP MEX manda no `termo-consentimento` chega à Granatech sem
  conferência; um aceite mal colhido é responsabilidade dele.
- Uma consulta de quem não passaria na triagem gasta cota que o agente usaria.

## Alternativas descartadas

- **Prova do SIM declarada e conferida** (resposta, momento, valores no texto).
  Tirada ao fechar o Saturday como proxy transparente: ele não interpreta o
  conteúdo do pedido além de cota, teto e escopo.
- **A integração dispara a conversa no WhatsApp** para colher o SIM. Deixaria
  a regra 3 intacta, mas o Saturday deixaria de ser só proxy.
- **Termo da Granatech pelo `link_termo`.** Só cobre a consulta, não a proposta.
