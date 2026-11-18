# 0029 — Dados do tomador conferidos antes da proposta

- **Data:** 2026-11-18
- **Status:** aceita
- **Desvia de:** especificação, "Especificação: jornada CLT, triagem e
  mensagens" (os dados do tomador vêm da Granatech)

## Contexto

A proposta do Crédito do Trabalhador leva data de nascimento, nome da mãe e
endereço do tomador. O agente lia os três da consulta da Granatech, mas só
conferia a mãe e o endereço antes de criar a proposta. Sem a data de
nascimento, a proposta era criada e só depois o envio dos dados do tomador era
recusado: a conversa ia para o atendente com uma proposta incompleta na
Granatech (issue 25).

## Decisão

- Antes de criar a proposta, o agente confere os três dados. A conferência roda
  quando o cliente diz que quer a proposta e de novo no SIM do resumo, antes da
  prova, da intenção gravada e do POST.
- **Data de nascimento:** vale a da Granatech. Se ela não devolver, entra a que
  o próprio cliente informou na identificação. É o único dos três que o agente
  aceita do cliente, porque já o pergunta em toda conversa.
- **Nome da mãe e endereço:** só os da Granatech. O agente não pede ao cliente.
- Faltando qualquer um dos três, handoff `dados_divergentes` antes da proposta,
  nunca depois. O handoff `dados_tomador_falhou` continua para o envio recusado
  por outro motivo, com a proposta já criada.

## Alternativas descartadas

- **Pedir a mãe e o endereço ao cliente** (endereço pelo CEP). Descartada por
  ora: não se sabe com que frequência a Granatech de produção deixa de devolver
  esses dados, e a api-dev devolve pouco por ser de teste. Rever com números
  reais depois do lançamento.
- **Marcar a proposta para um atendente conferir depois.** Mesma construção da
  alternativa acima, mais uma fila.

## Limites conhecidos

- A conferência é de presença. Um endereço presente com campos vazios passa e
  pode terminar em `dados_tomador_falhou`. Os campos obrigatórios do endereço
  não estão na especificação; é pergunta para a Granatech (`docs/granatech.md`).
