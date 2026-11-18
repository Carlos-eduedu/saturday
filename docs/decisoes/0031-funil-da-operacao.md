# 0031 — Funil da aba Operação: etapas, fontes e período

- **Data:** 2026-11-18
- **Status:** aceita

## Contexto

A especificação pede uma tela de números com funil, cota e custos; a aba
Operação tinha cota, custos e regras, sem funil (issue 35). O dono definiu o que
o funil mede: as etapas da jornada, por produto e por período (conversas
iniciadas, SIM dado, oferta apresentada, aceite, proposta criada, pago), nos
pontos em que o agente já grava algo no banco, com os números saindo do
servidor. Faltava dizer de onde sai cada número.

## Decisão

`GET /admin/funil?periodo=hoje|7d|30d|mes` (só gestor, como os custos; padrão
`mes`), em `painel/funil.py`. A resposta traz a contagem e a taxa de passagem
prontas; o painel não faz conta.

### De onde sai cada célula

| Etapa | Crédito do Trabalhador (CLT) | Portabilidade INSS (C6) | Contrato novo INSS (C6) | iCred (INSS) |
| --- | --- | --- | --- | --- |
| Conversas iniciadas | conversa com turno do público CLT | conversa com turno do público INSS | a mesma do INSS | a mesma do INSS |
| SIM dado | prova `consulta` | não se aplica | prova `simulacao_c6` | prova `icred_consulta` |
| Oferta apresentada | fala `oferta` ou `oferta_sem_seguro` | fala `inss:oferta` | fala `textos:oferta_contrato_novo` | fala `icred:oferta` |
| Aceite | turno com motivo `aceite_clt` ou `dados_divergentes`, turno na etapa `dados_proposta`, ou prova `proposta` | turno com motivo `aceitou_portabilidade` | turno com motivo `aceitou_contrato_novo` | prova `icred_aceite` |
| Proposta criada | `propostas_granatech` com `estado_envio = criada` | não se aplica | não se aplica | não se aplica |
| Pago | `propostas_granatech` com `status = PAYED` | não se aplica | não se aplica | não se aplica |

- **Provas:** tabela `consentimentos`, pelo `tipo`.
- **Falas de oferta:** `mensagens.chave_mensagem` de saída, pelo mesmo mapa que
  marca a oferta vigente na conversa (`RAMO_DA_OFERTA`, em `agent/service.py`).
  Oferta nova entra no funil ao entrar nesse mapa.
- **Aceite é o da oferta**, nos quatro produtos. No CLT ele deixa rastro
  diferente conforme a proposta automática (`SATURDAY_GRANATECH_PROPOSTA_ATIVA`):
  desligada, o handoff `aceite_clt`; ligada, a entrada na etapa
  `dados_proposta`, ou o handoff `dados_divergentes` quando faltam dados do
  tomador. A prova `proposta` (o SIM ao resumo, mais adiante) entra junto e
  não muda a conta: quem a tem passou por `dados_proposta`.
- **Público:** a conversa não tem coluna de público. Vale o que os turnos
  gravaram (`turnos`): `etapa = inss` ou classificação `inss` é INSS; etapa do
  CLT ou classificação `clt` é CLT. Uma conversa que passou pelos dois conta
  nos dois.
- **Nada do estado do grafo:** o checkpoint é podado pela retenção e não serve
  para contar.

### Etapas que um produto não tem

Aparecem como "não se aplica", nunca como zero, e ficam fora da taxa:

- **SIM na portabilidade:** a oferta sai do extrato que o cliente mandou, sem
  pedido de SIM. O SIM do C6 autoriza a simulação do contrato novo.
- **Proposta criada e pago no C6 e no iCred:** o aceite vai para um atendente,
  que digita no banco; o Saturday não grava a proposta nem o pagamento.

### Unidade

Conversas distintas: uma conversa conta uma vez por etapa e produto, mesmo com
dois SIM ou a oferta mostrada de novo.

### Período: coorte da conversa iniciada

Entram as conversas **iniciadas** no período (`conversas.criada_em`, no fuso da
operação), com todas as etapas a que chegaram depois, em qualquer data. Períodos:
hoje, 7 dias, 30 dias (os dois contando hoje) e mês atual.

A outra leitura, contar cada etapa pela data em que aconteceu, foi descartada:

- uma proposta paga hoje de uma conversa do mês passado daria "pago" maior que
  "proposta criada" no período, sem explicação na tela;
- "pago" não tem data própria: a tabela guarda o status atual da proposta, não
  quando ela foi paga.

O custo da coorte: o número de um período fechado ainda muda (a conversa de
ontem que aceita hoje sobe o "aceite" de ontem), e o funil não responde "quanto
foi pago nesta semana".

### Taxa de passagem

Porcentagem inteira sobre a etapa anterior **que o produto tem** (na
portabilidade, a oferta é medida contra as conversas iniciadas). Sem taxa na
primeira etapa e quando a anterior é zero.

### Conversas sem produto e de teste

- **Conversas iniciadas por produto:** a conversa começa num público, não num
  produto. As três colunas do INSS partem do mesmo número (as conversas do
  público INSS), e a tela diz isso.
- **Sem público definido** (só saudação, dúvida, público fora do piloto): não
  entra em coluna nenhuma. Aparece no total de conversas iniciadas do período,
  com a contagem "sem público definido" ao lado.
- **Conversa de membro testador** fica fora, pelo telefone, como nos custos
  (decisão 0020). Proposta com a marca `teste` também não conta. O vínculo é
  conferido na hora, como nos custos: quem deixa de ser testador volta ao
  funil com as conversas antigas (SIM, oferta e aceite; a proposta do
  simulador continua fora).

### Sem índice novo

A consulta filtra cada tabela pelas conversas da coorte: `mensagens` e `turnos`
já têm índice por conversa; `consentimentos` e `propostas_granatech` têm uma
linha por SIM e por proposta. Se a conta ficar lenta, o primeiro índice é
`consentimentos (conversa_id)`.

## Limites conhecidos

- **A conversa é uma por `conversation_id` do canal:** o cliente que volta
  meses depois na mesma conversa conta na coorte do primeiro contato, não
  como conversa nova.
- **Falas anteriores à decisão 0018** não têm `chave_mensagem`: a oferta delas
  não é contada, e o aceite pode passar de 100% da oferta.
- **Conversa apagada** leva os números junto (as tabelas apagam em cascata).
- **Aceite da portabilidade e do contrato novo:** não tem prova de
  consentimento; vale o motivo do handoff gravado no turno do aceite.
- **Seed do painel local** (`infra/painel_seed.py`), no mês atual: 21 conversas
  iniciadas, 15 sem público; CLT 2, 2, 2, 1, 1, 1; portabilidade 4, não se
  aplica, 2, 0; contrato novo 4, 2, 2, 1; iCred 4, 1, 1, 0.

## Alternativas descartadas

- **Período pela data de cada etapa:** acima.
- **Coluna de total por etapa:** somaria produtos com etapas diferentes (três
  ofertas contra dois SIM, porque a portabilidade não tem SIM) e voltaria a
  mostrar etapa posterior maior que a anterior.
- **Linha "sem produto" na tabela:** teria uma célula só; virou a contagem ao
  lado do total.
- **Contar pelo estado do grafo:** é podado e não se agrega em SQL.
