# 0024 — Comandos de chat do membro testador

- **Data:** 2026-11-16
- **Status:** aceita
- **Estende:** a 0020 (membro testador), que só tinha o `/reiniciar`

## Contexto

Testar uma etapa do fim da jornada CLT pedia refazer triagem, empresa e
identificação a cada vez. O resultado da consulta simulada só chegava se alguém
chamasse o `/admin/evento` do simulador, que não tem domínio. E testar handoff e
devolução pedia alguém no painel. O gestor pediu mais comandos no chat; o
comportamento foi validado num protótipo (ramo `prototipo/comandos-testador`).

## Decisão

Comando é a mensagem que começa com `/`, vinda do telefone de um membro com
`pode_testar_fluxos`. De cliente comum, o mesmo texto é mensagem qualquer.

| Comando | Efeito |
| --- | --- |
| `/ajuda` | Lista os comandos. |
| `/estado` | Etapa e passo, quem atende, cenário, consulta e dados coletados, com CPF, e-mail, celular, nascimento e nome mascarados. |
| `/reiniciar` | Como na 0020. O cenário volta para `sucesso`. Com humano, avisa que a conversa continua com humano. |
| `/humano` | Handoff com o motivo `pediu_humano` e o alerta de sempre. |
| `/devolver` | Devolve à IA, sem usuário e sem auditoria, como a liberação por prazo. Vale também quando um atendente assumiu a conversa de teste. |
| `/ir <etapa>` | Jornada CLT parada em `triagem`, `empresa`, `identificacao`, `consentimento`, `consultando` ou `oferta`, com dados fictícios. |
| `/cenario <resultado>` | Resultado da próxima consulta: `sucesso`, `sem_margem`, `erro` ou `termo_pendente`; e, com a consulta dando certo mas a pessoa sem o dado, `sem_nascimento`, `sem_mae` ou `sem_endereco` (issue 25). |

- **Antes do silêncio:** o comando responde mesmo com a conversa em handoff ou
  assumida. Só o `/ir` é recusado nesse estado.
- **Sem LLM:** comando não passa pelo grafo, fora o `/ir` que abre consulta. `/algo`
  desconhecido responde "Comando desconhecido" e não chega ao agente.
- **`/ir` e `/cenario` só com a Granatech simulada.** Sem o simulador
  (produção), os dois são recusados: pular a triagem ou o SIM diante da
  Granatech real quebraria as regras 3 e 5. O protótipo deixava pular até o
  consentimento em produção; a implementação é mais estrita.
- **`/ir` até `consentimento`** só grava o estado (`comandos.jornada_em`) e
  repete a pergunta da etapa. O consentimento para no pedido do SIM.
- **`/ir consultando` e `/ir oferta`** param no pedido do SIM e rodam um turno
  de sistema (`membro:ir`): a prova (`[teste de membro] /ir <etapa>`), a cota de
  teste e a consulta saem do mesmo código da jornada. `oferta` pede sucesso e
  fica com o primeiro vínculo, sem perguntar.
- **Cenário:** fica em `clt.cenario`. Com cenário, o cliente do simulador não
  reaproveita consulta do CPF: abre outra e manda `cenario` na query. O campo
  existe só no simulador; o cliente da Granatech real nunca o envia (regra 12).
- **Simulador manda o resultado sozinho:** consulta aberta com `cenario` recebe
  o webhook `atraso_detalhe_s` depois do termo (`SUCCESS`, `NO_MARGIN` ou
  `UNEXPECTED_ERROR`). Em `termo_pendente` o termo é recusado, o membro recebe
  o link e nenhum resultado chega. Toda consulta do cliente de teste leva
  cenário (`sucesso` quando o membro não escolheu), então a jornada digitada à
  mão também recebe o resultado.

## Consequências

- Cada `/ir consultando`, `/ir oferta` ou consulta depois de um `/cenario` gasta
  uma unidade da cota do parceiro `granatech_teste` (20 por dia, 500 por mês,
  os mesmos tetos da real). Esgotada, a conversa segue o fluxo de cota esgotada.
- `/ir` não chega a escolha de vínculo, proposta nem pós-venda, nem ao ramo INSS.
- O `/devolver` do membro tira a conversa de um atendente que a assumiu, sem
  registro de quem devolveu.
