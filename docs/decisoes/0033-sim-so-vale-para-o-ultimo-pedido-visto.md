# 0033 — O SIM só vale para o último pedido que o cliente viu

- **Data:** 2026-11-18
- **Status:** aceita
- **Complementa:** [decisão 0027](0027-icred-pelo-motor-da-mex.md) (issue 42) e
  [decisão 0008](0008-dados-da-proposta-antes-do-sim.md)

## Contexto

O que o atendente escreve pelo painel não entra no histórico do grafo. Na issue
42 o iCred passou a tratar isso: a devolução à IA deixa uma marca no histórico
e o pedido de antes do atendente deixa de valer. O ramo CLT, que está em
produção, ficou de fora: o agente pedia a autorização da consulta, um atendente
assumia, conversava e devolvia, o cliente respondia "sim" e a prova era gravada
e a consulta à Granatech aberta (com cota), para um pedido que não era a última
coisa que ele tinha visto. O aceite da oferta e o SIM ao resumo da proposta
tinham a mesma forma. O "Desfazer" do painel devolvia a conversa à IA sem a
marca, em qualquer ramo.

## Decisão

Do dono do produto, em 2026-11-18 (issue 44): **um SIM só vale para o último
pedido que o cliente viu, em todos os ramos.** Depois de um atendimento humano,
a IA mostra de novo o pedido ou a oferta, e só o "sim" seguinte vale.

- **Mecanismo, um só:** a devolução à IA (`AgentService._liberar_handoff`)
  acrescenta ao histórico a `marca_de_atendimento_humano` (mensagem vazia do
  agente, `agent/state.py`), e cada ramo lê `ultima_mensagem_agente`. Não há
  segunda forma de saber se houve atendimento.
- **Quem deixa a marca:** `devolver` pelo painel, o prazo do handoff, a rota
  `/release`, o `/devolver` do membro testador e, a partir desta decisão, o
  **"Desfazer" do painel quando o atendente escreveu ao cliente** entre o
  assumir e o desfazer (mensagem de saída com `autor = atendente` gravada
  depois do assumir) e a conversa volta à IA. Desfazer sem ter escrito não
  deixa marca: o pedido continua sendo a última coisa que o cliente viu, e o
  "sim" vale. Os outros desfazeres não voltam à IA e não mexem no histórico:
  desfazer um assumir de handoff volta ao handoff; desfazer um assumir tomado
  de outro atendente devolve a ele; desfazer um devolver volta a quem estava
  com a conversa (a marca do devolver fica, sem efeito enquanto um humano
  atende). Transferir não se desfaz.
- **CLT:** a conferência fica num ponto só, no despachante do nó
  (`agent/clt/nos.py`, `_refazer_pedido`), antes da etapa. Com a marca como
  última mensagem do agente, o "sim" não vale e a etapa mostra o pedido de
  novo, com a chave da mensagem (decisão 0018) e os valores do estado:
  - pedido de autorização da consulta: sem prova, sem consulta, sem cota;
  - oferta: o aceite não começa os dados da proposta;
  - resumo da proposta: sem prova, sem intenção e sem `POST` (regra 4); o
    resumo é montado de novo do estado e é o texto que vai para a prova do
    "sim" seguinte;
  - confirmações de sim ou não: celular do termo, nome da mãe, endereço,
    titular da conta (nos dados da proposta e na conta nova depois de falha de
    pagamento), opt-in do recontato por tempo de casa e as perguntas de sim ou
    não da triagem.
- **O que não muda no CLT:** "não", pergunta, pedido de mudança e resposta não
  reconhecida seguem para a etapa como antes, também depois da devolução. Nas
  etapas que esperam um evento (`consultando`, `proposta`, `formalizacao`) a
  devolução não refaz nada e um "sim" não cria consulta nem proposta. Sem
  atendente no meio, nenhum caminho mudou: a guarda só olha a marca.
- **iCred e C6:** como na issue 42. O "Desfazer" depois de o atendente escrever
  passa pela mesma liberação: no iCred o pedido ou a oferta sai de novo; no C6
  e na portabilidade pura o pedido (`aguardando`) e a oferta
  (`oferta_pendente`) são apagados, como em qualquer devolução.
- **Membro testador:** o `/ir` que para numa etapa põe a pergunta mostrada no
  histórico. Ela é o último pedido que o membro viu, mesmo logo depois de um
  `/devolver`. O `/ir` para `consultando` e `oferta` segue pelo turno de
  sistema, que não passa pela guarda.

## Limites conhecidos

- No CLT a guarda vale só para a primeira resposta depois da devolução:
  qualquer fala da IA passa a ser a última mensagem e desarma a marca. Se o
  cliente, devolvido, primeiro faz uma pergunta (a FAQ responde), manda algo
  não reconhecido (a etapa pede o SIM com o texto curto de repetição), responde
  "não" (a etapa não muda), manda um anexo ou o "não quero receber", e só
  depois responde "sim", o "sim" vale para o pedido de antes do atendente, com
  a prova do texto antigo. O iCred não tem esse caso, porque compara a última
  mensagem com o texto do pedido. Fechar isso no CLT muda o tratamento de
  dúvida do ramo, o que a issue 44 deixou de fora: **falta a decisão do dono**.
- A marca não sabe se alguém falou com o cliente. O prazo do handoff vencido
  e a rota `/release` (inclusive em conversa que já estava com a IA) deixam a
  marca mesmo sem atendimento: nesses casos o CLT pede o SIM uma segunda vez.
- O "Desfazer" só existe por 15 segundos depois do assumir
  (`PRAZO_DESFAZER`): o caso "assumiu, escreveu e desfez" é raro. A fala do
  atendente é reconhecida pela hora de gravação (`criada_em`, a hora de início
  da transação): um envio e um assumir quase simultâneos do mesmo usuário podem
  ficar fora de ordem e a marca não sair. Mensagem do atendente que falhou na
  entrega conta como escrita.

## Alternativas descartadas

- **Conferir o texto da última mensagem no CLT, como o iCred:** mudaria a
  dúvida no meio, o extrato e a mensagem vazia num ramo em produção; a issue
  pediu só a devolução.
- **Zerar a etapa do CLT na devolução:** perderia os dados já informados.
- **Marca em todo "Desfazer":** quem assume por engano e desfaz sem falar não
  atendeu ninguém; o pedido ainda é a última coisa que o cliente viu.

## Consequências

- Testes em `apps/core/tests/test_clt_devolucao.py` (CLT e o "Desfazer") e em
  `tests/test_consentimento_pontas.py` (iCred, C6 e portabilidade).
- `POST /admin/conversas/{id}/desfazer` passa pelo `AgentService.desfazer`,
  que escreve no checkpoint sob a trava da conversa e antes do commit do
  banco, na mesma ordem do `devolver`.
