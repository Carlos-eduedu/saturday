# 0027 — iCred no ramo INSS, pelo motor de consultas da MEX

- **Data:** 2026-11-16
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, regra 1 (sistema da MEX), regra 2 (escolha de
  produto), regra 6 (teto) e "Fora do escopo"

## Contexto

A operação quer oferecer o iCred (INSS: portabilidade, portabilidade com
refinanciamento, refinanciamento e contrato novo) pelo agente. O iCred não tem
API. O que existe é o "motor de consultas", um sistema da MEX mantido pela
Dynatech: um robô de navegador que opera o portal do iCred com logins de
operador e expõe uma API HTTP com chave por aplicação e webhook assinado. O
que a especificação e o código-fonte do motor dizem está em `docs/icred.md`.

O motor decide muita coisa sozinho: escolhe a tabela de maior comissão, grava
de uma vez uma proposta por contrato do cliente, não aceita valor máximo e não
informa o status da proposta depois da gravação.

## Decisão

**Exceção à regra 1.** O Saturday chama o motor de consultas do iCred, mesmo
sendo sistema da MEX. A exceção vale só para esse motor, com chave própria do
Saturday e escopos `consultas` e `consultas:gravar`. O escopo `operacao` não é
pedido: o Saturday não lê dados de outras aplicações (`GET /clientes/{cpf}`,
`GET /gravados`), não opera logins e não roda conferência. CRM, Supabase e os
hubs da MEX continuam proibidos.

**Lugar na jornada.**

- O iCred é o segundo banco do ramo INSS, com os quatro tipos de produto.
- A consulta acontece depois do extrato lido; o extrato continua obrigatório.
- Antes de consultar, o agente pede um SIM próprio, com texto fixo que cita o
  banco e o uso do CPF e do telefone, e grava a prova (regra 3). Só então envia
  `lgpd_ok: true`.
- Sem oferta, com erro ou com demora além do prazo, a conversa segue o caminho
  de antes (portabilidade C6 pelo extrato e handoff), sem avisar o cliente.
  Consulta parada abre alerta.
- `JA_GRAVADO`, `PROPOSTA_EXISTENTE` e `TELEFONE_VINCULADO` vão para handoff com
  o motivo.

**Oferta.**

- O motor escolhe a tabela (desvio da regra 2). O Saturday confere em código o
  que apresenta.
- A oferta é o pacote inteiro que o motor devolve: cada contrato (banco,
  parcela, prazo, valor na conta) e o total. O aceite vale para o pacote,
  porque o motor grava tudo junto.
- Se qualquer contrato do pacote tiver taxa acima de 1,85% ao mês, a conversa
  vai para handoff sem oferta (mesma política da decisão 0026).
- Entre bancos, o agente apresenta uma oferta só: a de maior valor na conta do
  cliente, com o C6 ganhando no empate.
- O teto de R$ 6.999 (regra 6) vale só para o CLT.
- Comissão (`comissao_rs`, `pct`, `comissao`) é descartada na leitura: não
  entra no estado, na ficha nem em log.

**Proposta.**

- Nunca `acao: gravar` direto em `POST /consultas` nem `aceitar_mudanca: true`:
  os dois gravam o que o cliente não viu.
- A consulta vale 15 minutos. Aceite depois disso usa `vencida_ok: true` (o
  motor só grava se as ofertas forem idênticas). `RECALCULO` pede consulta nova
  e aceite novo.
- O agente só grava sozinho os tipos `novo` e `refin` (parâmetro `produtos`).
  Pacote com `port` ou `port_refin` é apresentado como estimativa e o atendente
  grava: nesses tipos o valor gravado pode diferir do mostrado.
- Depois de gravar, o agente avisa que o link de assinatura chega pelo iCred
  por WhatsApp ou SMS e para; a equipe acompanha.
- Resultado incerto na gravação vira alerta para um humano conferir no portal.
  Sem nova tentativa (regra 4).

**Entrega em duas fases.**

1. Consulta, oferta e aceite com prova; a conversa passa ao atendente, que
   grava pelo painel do motor.
2. Gravação pelo agente, atrás de flag, condicionada aos pedidos abaixo.

**Código.** `bancos/icred/` ao lado de `bancos/granatech/`, sem interface comum
(ver a nota na decisão 0004). Simulador novo em `simuladores/icred`, feito a
partir do código-fonte do motor; o motor de verdade só em produção (regra 11),
porque a consulta real já cria lead no iCred. No painel, só uma seção na aba
Bancos e a consulta e a proposta na ficha.

## Pedidos ao motor (condição da fase 2)

- Devolver o valor realmente gravado em cada proposta.
- Gravar um contrato específico, não o pacote inteiro.
- Mandar o status da proposta por webhook (assinada, paga, cancelada,
  reprovada) e rodar a conferência sem pedido manual.
- Dizer, depois de uma queda no meio da gravação, se a proposta foi criada, em
  vez de `JA_GRAVADO`.
- Avisar quando a consulta fica parada na fila pelo limite diário do login.

## Riscos conhecidos

- O motor grava com cadastro fictício fixo (nascimento `2000-01-01`, e-mail
  genérico); o cliente completa os dados no link do iCred.
- Só aparece oferta com comissão maior que zero: oferta boa para o cliente e sem
  comissão volta como `SEM_COMISSAO`.
- "Um CPF é gravado uma vez" é global e permanente no motor; não há como
  atender de novo pelo motor um cliente já gravado.
- O motor guarda CPF, telefone e nome em claro e sem prazo de expurgo.
- `GET /eventos?desde=` pode pular evento criado no mesmo segundo: o webhook é a
  fonte principal e a consulta por id confirma.
- O motor depende do portal do iCred (Cloudflare, login do operador, IP do
  servidor) e pode parar sem aviso.

## Pendências

- `TODO(icred): a oferta tem seguro? Onde aparecem o valor e o CET?` O motor não
  lê esses campos. Até a operação responder, a oferta não cita seguro (regra 7).
- `TODO(icred): o que o cliente faz no link de assinatura (dados, documentos,
  biometria, conta)?`
- Cadastro da aplicação do Saturday no motor (chave, `webhook_url`,
  `segredo_webhook`), por quem opera o motor.

## Alternativas descartadas

- **Manter a regra 1 e não integrar.** O iCred não tem API oficial; sem o motor
  o produto fica só com o atendente.
- **Robô próprio do Saturday no portal.** Duplicaria o motor e disputaria os
  mesmos logins de operador.
- **Pedir o escopo `operacao` para acompanhar a proposta.** Abre dados de outras
  aplicações e o controle dos logins; o acompanhamento espera o webhook de
  status.
- **Apresentar parte do pacote e gravar tudo.** Quebra a regra 3.
- **Aplicar o teto de R$ 6.999.** No INSS o valor costuma passar disso e o motor
  não aceita valor máximo.

**Nota de 2026-11-18.** Com o C6 (decisão 0026) e o iCred ligados juntos,
decidido com o dono do produto na issue 22: são dois SIMs em momentos separados,
um por banco, cada um pedido só quando a consulta daquele banco vai acontecer;
os dois pedidos não viram um e a ordem do grafo não muda. Depois de o cliente
recusar o contrato novo do C6 o iCred continua sendo consultado, e o contrato
novo recusado não conta na comparação: o iCred é comparado só com a
portabilidade. Mudou só o texto do pedido de SIM do iCred quando o cliente já
respondeu ao pedido do C6: a abertura deixa de citar a chegada do extrato, com
versão própria na prova (`icred-1-depois-c6`). Regra decidida no mesmo dia: o
SIM vale só para o último pedido mostrado. Extrato novo, inclusive de outro
titular, cancela o pedido de SIM do iCred ainda sem resposta, e o iCred
pergunta de novo na vez dele; nenhuma prova `icred_consulta` é gravada por um
SIM dado a um pedido do C6, nem o contrário. Os caminhos estão em
`docs/icred.md`. Fechando a issue no mesmo dia: extrato de outro titular
descarta o que o iCred tinha do titular anterior (pedido, consulta aberta e
oferta) e o iCred recomeça do pedido de SIM para o novo; e o SIM que não
responde à última mensagem do agente refaz o pedido em vez de gravar a prova,
como o C6 já fazia. Dois ajustes do dono do produto, ainda no mesmo dia: a
dúvida feita logo depois de um pedido do iCred é respondida e o pedido sai de
novo no mesmo turno, por último, de modo que o SIM seguinte vale; e no pedido
de CPF refaz-se só o pedido do CPF, sem descartar o SIM já dado. Na issue 42,
no mesmo dia: CPF digitado diferente do CPF do extrato não é consultado (o
agente pede de novo e, na segunda vez, passa ao atendente), e depois de um
atendente devolver a conversa à IA o "sim" não aceita pedido nem oferta de
antes dele: a IA mostra de novo, e só o "sim" seguinte vale. E no pedido de
CPF só a afirmação curta ("ok", "sim", "tá bom") recebe o pedido de novo sem
passar pela triagem; o resto vai para o classificador, como antes.
