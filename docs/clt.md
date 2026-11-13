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

## Turnos de sistema

`AgentService.continuar(conversation_id, evento)` roda o grafo sem mensagem do
cliente, sob a trava da conversa, e grava a resposta no outbox. Se a conversa
estiver em handoff ou assumida, não roda e abre o alerta `evento_com_humano`.
Os eventos são estes:

| Evento | Quem dispara | Efeito |
| --- | --- | --- |
| `consulta_pronta` | `jobs/granatech` no `SUCCESS` | Vínculo e oferta |
| `consulta_sem_margem` | `NO_MARGIN` | Não elegível |
| `consulta_erro:<status>` | `USED`, `UNEXPECTED_ERROR` e os de significado pendente | Handoff |
| `termo_pendente` | `jobs/alertas`, consulta parada em `AWAITING_CLIENT_AUTHORIZATION` | Link do termo |
| `recontato:<n>` | `jobs/recontatos` | Nova tentativa de consulta |

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
também vai para handoff, porque o contrato da proposta sem seguro é pendente.

- **Dados:** confirma o nome da mãe e o endereço da Granatech (se divergirem,
  handoff), pede o estado civil e a conta, um dado por mensagem: banco por nome
  ou código (lista `GET /bancos` com cache de 1 dia), tipo, agência, conta com
  dígito e "a conta está no seu CPF?".
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

## Testes

- `tests/test_clt_regras.py` e `tests/test_clt_mensagens.py`: sem rede nem banco.
- `tests/test_clt_proposta.py`: proposta e pós-venda, com timeout simulado no
  POST, cada status de proposta e o link curto.
- `tests/test_clt_jornada.py`: jornadas com Postgres, o simulador da Granatech em
  processo e uma BrasilAPI falsa. Sem `SATURDAY_TEST_DATABASE_URL`, esses testes
  são pulados.
