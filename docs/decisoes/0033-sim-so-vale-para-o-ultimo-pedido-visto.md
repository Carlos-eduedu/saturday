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

## Nota de 2026-11-18 (issues 45 e 46)

Duas decisões do dono do produto, do mesmo dia, mudam o que está acima. Onde
esta nota e o texto de cima divergem, vale a nota.

**1. A marca vale até o pedido ser mostrado de novo (CLT).** Depois de uma
devolução com atendimento, nenhum "sim" vale para um pedido do CLT enquanto
esse pedido não aparecer de novo, qualquer que seja a fala da IA no meio
(resposta a uma dúvida, "não entendi", recusa, opt-out).

- **Desenho:** continua um mecanismo só, a marca no histórico. O despachante do
  CLT deixa de perguntar "a marca é a última mensagem do agente?" e passa a
  perguntar "o pedido desta etapa apareceu depois da última marca?"
  (`falas_desde_o_atendimento`, em `agent/state.py`). Havendo marca, se a
  resposta do cliente é um "sim" ao pedido da etapa (`_refazer_pedido`, o mesmo
  leitor de antes) e nenhuma fala do agente depois da marca termina com o texto
  desse pedido, o pedido sai de novo, sem prova, consulta, cota nem proposta.
  Com o pedido mostrado, o "sim" seguinte vale. Sem marca no histórico, o
  despachante não entra na conferência: nenhum caminho de cliente sem
  atendente mudou.
- **Por que não um campo "falta refazer" no estado do CLT:** seria um segundo
  registro do mesmo fato, para manter em sincronia com a marca, e teria de ser
  desligado em todo lugar que mostra um pedido (`perguntar`, a oferta, o
  resumo, o `/ir`). A posição da marca em relação ao pedido já diz isso.
- **Por que não reenviar o pedido no mesmo turno, depois da resposta:** mudaria
  o que o cliente recebe na dúvida, na recusa e no opt-out (um "não" seguido
  do pedido de novo), exigiria passar pela FAQ e voltar ao nó do CLT, e na
  recusa do resumo o pedido da etapa muda no meio do turno.
- **O que conta como "mostrado de novo":** qualquer fala do agente, depois da
  marca, que termine com o texto do pedido da etapa. Vale para o pedido refeito
  pela guarda, para a pergunta feita pelo andar normal da jornada (a marca
  ficou para trás), para a oferta nova depois de um pedido de mudança, para a
  pergunta posta pelo `/ir` e para a resposta a um anexo, que traz a pergunta
  inteira (`sem_documento`) ou o resumo (issue 46).
- **Recusa continua recusa:** "não" ao pedido da consulta, à oferta e ao resumo
  segue para a etapa como antes. Depois do "não" ao resumo a jornada volta à
  oferta, que foi vista antes do atendente: o "sim" seguinte mostra a oferta de
  novo em vez de começar os dados da proposta.
- **iCred e C6:** conferidos, sem mudança. O iCred compara o texto da última
  fala com o pedido, e a resposta à dúvida não é o pedido; o C6 e a
  portabilidade perdem o pedido e a oferta em toda devolução.

**2. A marca só existe se um atendente escreveu ao cliente.** Toda volta à IA
passa por `AgentService._liberar_handoff` (devolver, prazo do handoff,
`/release`, `/devolver` do membro testador e o "Desfazer"), e é lá, num lugar
só, que a fala do atendente é conferida.

- **"Escreveu":** existe em `mensagens` uma linha com `autor = atendente`
  nessa conversa (texto, mídia ou modelo enviados pelo painel), entregue ou
  não. A que falhou na entrega conta: o cliente pode ter recebido.
- **"Desde quando":** desde que a conversa saiu do estado `ia`, por handoff ou
  por assumir, qualquer que seja o atendente (um pode ter escrito e outro
  assumido depois, ou a conversa assumida pode ter caído em handoff). Como o
  painel só deixa escrever com a conversa assumida, isso é o mesmo que "fala de
  atendente que nenhuma volta à IA contou ainda": o estado do grafo guarda o id
  da última fala já contada (`fala_atendente`), e a liberação compara com o
  maior id de fala de atendente da conversa
  (`repositorios.ultima_fala_de_atendente`). Não depende de relógio.
- **Sem fala nova:** não há marca. O pedido continua sendo a última coisa que o
  cliente viu, e o "sim" vale (CLT e iCred).
- **O que não mudou:** a liberação continua zerando `aguardando`,
  `oferta_pendente` e as contagens, com ou sem fala do atendente; no C6 e na
  portabilidade o "sim" depois de qualquer devolução continua sem ter o que
  aceitar. O "Desfazer" sem fala continua sem tocar no checkpoint. O `/ir`
  continua sem marca.

**Limites conhecidos que deixam de existir:** o primeiro (a guarda do CLT só
na primeira resposta), o segundo (a marca sem ninguém ter falado com o
cliente) e, no terceiro, a ordem pela hora de gravação (`criada_em`) no
"Desfazer".

**Limites conhecidos que ficam ou aparecem:**

- Conversa que já tinha fala de atendente antes desta mudança não tem
  `fala_atendente` no estado: a primeira volta à IA depois do deploy conta a
  fala antiga e deixa a marca, mesmo sem atendimento novo (o comportamento de
  antes, uma última vez). O mesmo acontece depois de um `/reiniciar`, que apaga
  o estado. Erra para o lado seguro: um pedido a mais, nunca um "sim" aceito.
- Marca deixada antes desta mudança (inclusive por prazo ou `/release` sem
  atendimento) continua no histórico e passa a valer até o pedido reaparecer:
  nessas conversas, um "sim" dado depois de outra fala da IA, que antes valia,
  recebe o pedido mais uma vez.
- No iCred, quando a conversa saiu da IA por um handoff do próprio grafo, o
  aviso de handoff é a última fala do agente: mesmo sem marca, o "sim" de
  depois do prazo refaz o pedido (o cliente viu o aviso depois do pedido). Já
  era assim; o "sim vale" sem atendente é o do assumir direto e o do CLT.
- Turno de sistema não passa pela guarda. O recontato por cota esgotada abre a
  consulta com a prova já gravada, mesmo que um atendente tenha escrito no
  meio; não há "sim" novo nesse caminho. Já era assim.
- No "Desfazer" desse mesmo caso (conversa antiga, assumir por engano e
  desfazer sem escrever), a liberação roda uma vez e zera o pedido do C6.
- A comparação é pelo texto. Se o texto de uma mensagem fixa mudar entre o
  pedido e o "sim" de uma conversa que teve atendimento, o pedido sai mais uma
  vez.
- A resposta a um anexo conta como pedido mostrado de novo, porque traz o
  pedido inteiro; a prova guarda o texto do pedido, não a frase que vem antes.
- Mensagem do atendente que falhou na entrega conta como escrita.

Testes: `tests/test_clt_devolucao.py` (as falas no meio, a volta sem fala, o
segundo atendente, a fala antiga), `tests/test_consentimento_pontas.py` (iCred
e C6) e `tests/test_clt_anexo.py` (issue 46).
