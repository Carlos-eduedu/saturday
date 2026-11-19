# Ramo CLT (fases 5 e 6)

Jornada do Crédito do Trabalhador da primeira mensagem até o pagamento. Os
termos (triagem, consulta, vínculo, oferta, aceite, proposta, formalização, não
elegível, recontato) estão no [`GLOSSARY.md`](../GLOSSARY.md).

## Ligar

Com `SATURDAY_GRANATECH_ATIVO=true`, a API e o worker montam o cliente da
Granatech e a BrasilAPI no contexto do grafo (`web/composicao.py`). A conversa
entra no ramo quando o Jev classifica o público como `clt` e nenhuma jornada
INSS está em curso. Com a flag desligada, quem é CLT continua sendo atendido
pela FAQ, como antes.

Para o cliente chegar lá, uma saudação sem jornada em curso (intenção
`saudacao` do Jev, com probabilidade ≥ 0,95, medida em
`tests/test_jev_avaliacao.py`) recebe boas-vindas fixas que
perguntam o público, sem chamar o LLM (`agent/nodes.py:boas_vindas`). O
critério `clt` do Jev também aceita quem pede o Crédito do Trabalhador,
empréstimo CLT ou consignado privado, e o público só troca com probabilidade
≥ 0,8 (negar um público cai em `indefinido`). Fora de jornada, a primeira resposta sem
FAQ vira "não entendi" com o que o agente faz; só a segunda seguida vai para a
equipe (`tentativas_resposta`). Dentro de uma jornada, sem FAQ é handoff na
hora, como antes.

## Onde está cada coisa

| Arquivo | O que faz |
| --- | --- |
| `conhecimento/clt/mensagens.yaml` | Todo texto que o cliente lê no ramo, com `versao` |
| `apps/core/src/saturday/agent/clt/mensagens.py` | Carrega o YAML (procura a partir do diretório atual) e preenche as variáveis |
| `agent/clt/leitura.py` | Leitura das respostas: sim/não, tempo de casa, CPF, CNPJ, nome, data, sexo, e-mail, celular, regra do SIM, pedidos depois da oferta |
| `agent/clt/regras.py` | Idade × prazo, recontato por tempo de casa, vínculo, produto e empresa |
| `agent/clt/nos.py` | O nó `clt`: uma função por etapa e os turnos de sistema |
| `fontes/brasilapi.py` | CNPJ na BrasilAPI, com cache de 30 dias em `empresas_cnpj` |
| `dados/consentimentos.py` | Prova do SIM |
| `dados/recontatos.py`, `jobs/recontatos.py` | Recontatos e o disparo pelo worker |
| `agent/clt/turno.py` | O `Turno`: estado da jornada e as saídas comuns às etapas |
| `agent/clt/proposta.py` | Dados da proposta, aceite, criação e pós-venda |
| `dados/links.py`, `web/api/links.py` | Link curto da biometria (`GET /l/{codigo}`) |

## Etapas

`triagem` → `empresa` → `identificacao` → `consentimento` → `consultando` →
`escolha_vinculo` → `oferta`. As saídas são `nao_elegivel`, `recontato` e
handoff. A triagem vem antes da identificação
([decisão 0007](decisoes/0007-triagem-antes-da-identificacao.md)).

- **Triagem:** carteira assinada, tempo de casa, contrato especial, empréstimo
  na Granatech e 30 funcionários, uma pergunta por vez. Com menos de 12 meses de
  casa, grava um recontato `tempo_casa` para a data em que o cliente completa
  12 meses.
- **Empresa:** CNPJ com dígito verificador. A empresa é reprovada se não estiver
  ATIVA, tiver menos de 24 meses, for MEI ou microempresa, ou se a razão social
  indicar recuperação, falência ou liquidação. Se a BrasilAPI falhar duas vezes,
  a conversa vai para handoff.
- **Identificação:** CPF, nome, nascimento e sexo, um por mensagem. Sem nenhum
  prazo permitido (57 anos para mulher, 62 para homem, mínimo de 21), o cliente
  não é elegível.
- **Consentimento:** e-mail e confirmação do celular do WhatsApp (mascarado; se
  o cliente negar, pede outro). Depois vem o texto fixo do SIM. A prova vai para
  `consentimentos` antes de qualquer consulta, e a consulta confere que a prova
  existe. Depois o agente assina o termo pela API; se falhar, envia o
  `link_termo_consentimento`.
- **Consulta:** usa `abrir_consulta` do cliente (reaproveitamento, cota). Uma
  consulta reaproveitada e pronta segue no mesmo turno. As outras esperam o
  webhook.
- **Vínculo e oferta:** com um vínculo ofertável, ele é escolhido sem perguntar.
  Com vários, o cliente escolhe numa lista numerada. A simulação usa a margem
  inteira e o produto de maior comissão dentro do limite de idade, e o teto
  reduz a parcela quando precisa. Antes, a idade × prazo é conferida de novo com
  o sexo e o nascimento da Granatech.
- **Depois da oferta:** o cliente pode pedir "sem seguro", outro prazo ou outra
  parcela, que são lidos em código. São no máximo 5 novas simulações; depois,
  handoff.

Uma resposta não reconhecida faz a pergunta se repetir; dois erros seguidos no
mesmo dado levam a handoff. Texto com `?` vai para a FAQ sem mudar a etapa. Em
`nao_elegivel`, só a FAQ responde, e só um atendente reabre a conversa.

Anexo no meio da jornada não é lido: a resposta é `sem_documento` com a
pergunta do passo (quando ela é um texto sem variáveis). No resumo da proposta
(`aceite`), cujo passo também se chama `sim`, o anexo recebe o resumo de novo,
montado do estado, e é esse o texto da prova do "sim" seguinte (issue 46; antes
saía o pedido de autorização da consulta). Testes em `tests/test_clt_anexo.py`.

## Atendente no meio

Um SIM só vale para o último pedido que o cliente viu
([decisão 0033](decisoes/0033-sim-so-vale-para-o-ultimo-pedido-visto.md) e a
nota de 2026-11-18 nela, issue 45). Quando a conversa volta à IA depois de um
atendente ter escrito ao cliente, a volta deixa no histórico a marca de
atendimento humano (a mesma do iCred, `docs/icred.md`). Enquanto o pedido da
etapa não aparecer de novo depois da marca, o "sim" não vale e a etapa mostra o
pedido, com a chave da mensagem e os valores do estado. Só o "sim" seguinte
vale, com a prova do texto mostrado. A conferência fica num ponto só, no nó
`clt`, antes da etapa (`agent/clt/nos.py`): `falas_desde_o_atendimento`
(`agent/state.py`) diz o que o agente falou depois da marca e
`_refazer_pedido` monta o pedido da etapa.

Sem fala de atendente desde que a conversa saiu da IA (prazo do handoff
vencido sem ninguém assumir, `/release`, devolver sem ter escrito), não há
marca: o pedido ainda é a última coisa que o cliente viu, e o "sim" vale.
Mensagem do atendente que falhou na entrega conta como escrita.

| Etapa e passo | "Sim" antes de o pedido aparecer de novo |
| --- | --- |
| `consentimento` / `sim` | Pedido de autorização de novo; sem prova, consulta ou cota |
| `oferta` | A oferta de novo; os dados da proposta não começam |
| `aceite` / `sim` | O resumo de novo, montado do estado; sem prova, intenção ou `POST` |
| `consentimento` / `confirmar_celular` | A confirmação do celular de novo |
| `dados_proposta` / `mae`, `endereco`, `titular` | A confirmação de novo |
| `nova_conta` / `titular` | A confirmação de novo |
| `recontato` / `optin` | O pedido de aviso de novo; sem opt-in nem recontato |
| `triagem` (perguntas de sim ou não) | A pergunta de novo |
| `consultando`, `proposta`, `formalizacao` | Nada muda: a etapa espera o evento |

"Não", pergunta, pedido de mudança e resposta não reconhecida seguem para a
etapa como sempre, e nenhuma dessas respostas da IA mostra o pedido: o "sim"
que vier depois delas ainda recebe o pedido de novo. Depois do "não" ao resumo
a jornada volta à oferta, e o "sim" seguinte mostra a oferta de novo. Conta
como pedido mostrado qualquer fala do agente, depois da marca, que termine com
o texto do pedido: o pedido refeito, a pergunta do andar normal da jornada, a
oferta nova depois de um pedido de mudança e a resposta a um anexo, que traz a
pergunta inteira. Cliente que nunca teve atendente não passa pela conferência.
Testes em `tests/test_clt_devolucao.py`.

## Turnos de sistema

`AgentService.continuar(conversation_id, evento)` roda o grafo sem mensagem do
cliente, sob a trava da conversa, e grava a resposta no outbox. Se a conversa
estiver em handoff ou assumida, não roda e abre o alerta `evento_com_humano`.
Os eventos são estes:

| Evento | Quem dispara | Efeito |
| --- | --- | --- |
| `consulta_pronta` | `jobs/granatech` no `SUCCESS` | Vínculo e oferta |
| `consulta_sem_margem` | `NO_MARGIN` | Não elegível |
| `consulta_erro:<status>` | `USED` e `UNEXPECTED_ERROR` | Handoff |
| `termo_pendente` | `jobs/alertas`, consulta parada em `AWAITING_CLIENT_AUTHORIZATION` | Link do termo |
| `recontato:<n>` | `jobs/recontatos` | Nova tentativa de consulta |

Se o grafo falhar num turno de sistema, a exceção sobe para quem chamou e o
turno com erro fica na trilha (gravado em transação própria, porque a do turno
é desfeita). A fila de eventos tenta de novo até `eventos_max_tentativas`;
quando desiste de um evento da Granatech, a conversa vai para handoff
`erro_interno` com alerta, sem aviso ao cliente. Se ela já estiver com humano,
abre só o alerta `evento_com_humano`. Rotas do painel e `jobs/alertas` não
tentam de novo: o erro volta para quem pediu.

Só a etapa `consultando` reage aos eventos de consulta. Um evento repetido ou
atrasado não gera mensagem.

## Cota esgotada

O cliente ouve que o agente volta a falar no dia seguinte. O recontato
`cota_esgotada` é marcado para as 9h (`America/Sao_Paulo`). No disparo, a
consulta é tentada de novo. Se a cota continuar esgotada, o recontato é
remarcado até 3 vezes; na 4ª falha, a conversa vai para handoff.

## Proposta e pós-venda (Fase 6)

Com `SATURDAY_GRANATECH_PROPOSTA_ATIVA=true`, quando o cliente quer seguir com a
oferta, a jornada continua: `dados_proposta` → `aceite` → `proposta` →
`formalizacao` → `pago` ([decisão 0008](decisoes/0008-dados-da-proposta-antes-do-sim.md)).
Com a flag desligada, o aceite vai para handoff (`aceite_clt`). Oferta sem seguro
segue o mesmo caminho da com seguro: a proposta vai sem o bloco
`informacaoDeSeguros` (resposta da Granatech, 2026-11-16; na homologação todo
produto tem seguro, então esse corpo só roda em produção).

- **Dados:** antes de qualquer pergunta, confere os três dados do tomador que
  o banco exige: nascimento, nome da mãe e endereço. O nascimento é o da
  Granatech; se ela não devolver, vale o que o cliente informou na
  identificação; sem nenhum dos dois, handoff `dados_divergentes`
  ([decisão 0029](decisoes/0029-dados-do-tomador-conferidos-antes-da-proposta.md)).
  Confirma o nome da mãe e o endereço da Granatech; se faltarem, ou se o
  cliente disser que estão errados, ele informa: o nome completo da mãe, e o
  endereço pelo CEP (BrasilAPI, com confirmação), número e complemento; CEP não
  achado, pede rua, bairro, cidade e UF
  ([decisão 0034](decisoes/0034-mae-e-endereco-informados-pelo-cliente.md)). A
  conferência dos três dados roda de novo no SIM do resumo, antes da prova, da
  intenção e do POST. Depois pede o estado civil ("união estável" grava
  `SOLTEIRO`) e a conta, um dado por mensagem: banco por nome ou código (lista
  `GET /bancos` com cache de 1 dia), tipo, agência, conta com dígito e "a conta
  está no seu CPF?".
- **Aceite:** o resumo traz valores, seguro e a conta mascarada. O SIM é gravado
  como prova `proposta` (com o texto exato do resumo) antes do POST.
- **Proposta:** `criar_proposta` (intenção gravada, um POST só, reconciliação
  pela listagem) e depois `dados-tomador`. Resultado incerto sem proposta achada
  vai para handoff `proposta_incerta`, sem novo POST.
- **Pós-venda:** cada evento de proposta que muda o status vira o turno de
  sistema `proposta:<acao>` (`status.acao_da_proposta`). Evento repetido,
  atrasado ou de "só atualiza" não gera mensagem. Revisão do banco, status
  desconhecido, pedido de cancelamento e segunda falha de pagamento vão para
  handoff.
- **Falha de pagamento:** o agente pede outra conta. Com
  `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO` desligada (padrão), vai para handoff
  com a conta no alerta; ligada, faz o PATCH.
- **Biometria:** um link curto por proposta,
  `https://{SATURDAY_DOMINIO_PUBLICO}/l/{codigo}`. No clique, a API busca o
  `url_seguranca_identidade` vigente; se a Granatech falhar, usa o último
  conhecido.
- **Janela de 24 h fechada:** cada aviso diz o modelo que o substitui
  (`assinatura_pronta` e `assinatura_refazer` com o código do link,
  `dados_bancarios_pendentes`, `pagamento_confirmado`; os demais,
  `atualizacao_pedido`). O texto completo espera o cliente responder.

## Recontato por tempo de casa (Fase 6)

Com menos de 12 meses de casa, o agente pergunta se pode avisar quando o cliente
completar. O SIM grava `conversas.marketing = opt_in` e o recontato
`tempo_casa`; na data, o worker envia o modelo de marketing
`recontato_tempo_casa` e a jornada recomeça pela triagem. "Não quero receber"
grava `opt_out` em qualquer etapa, e o recontato não sai.

## Comandos do membro testador

Na conversa de membro testador, `/ajuda`, `/estado`, `/reiniciar`, `/humano` e
`/devolver` valem sempre; `/ir <etapa>` e `/cenario <resultado>` só com a
Granatech simulada ([decisão 0024](decisoes/0024-comandos-do-membro-testador.md)).
A leitura e os textos ficam em `agent/comandos.py`; quem executa é o
`AgentService._executar_comando`, antes do silêncio com humano. O `/ir` para
`consultando` ou `oferta` vira o turno de sistema `membro:ir`, que segue do
pedido do SIM pelo mesmo `_autorizou` da jornada. O `/ir` que para numa etapa
põe a pergunta mostrada no histórico do grafo: é o último pedido que o membro
viu, mesmo logo depois de um `/devolver`. Os testes estão em
`tests/test_membros_testadores.py`.

## Testes

- `tests/test_clt_regras.py` e `tests/test_clt_mensagens.py`: sem rede nem banco.
- `tests/test_clt_proposta.py`: proposta e pós-venda, com timeout simulado no
  POST, cada status de proposta e o link curto.
- `tests/test_clt_jornada.py`: jornadas com Postgres, o simulador da Granatech em
  processo e uma BrasilAPI falsa. Sem `SATURDAY_TEST_DATABASE_URL`, esses testes
  são pulados.
