# Ramo CLT (Fase 5)

Jornada do Crédito do Trabalhador da primeira mensagem até a oferta. O aceite
ainda vai para um especialista (handoff `aceite_clt`); a proposta entra na
Fase 6. Os termos (triagem, consulta, vínculo, oferta, não elegível, recontato)
estão no [`GLOSSARY.md`](../GLOSSARY.md).

## Ligar

Com `SATURDAY_GRANATECH_ATIVO=true`, a API e o worker montam o cliente da
Granatech e a BrasilAPI no contexto do grafo (`web/composicao.py`). A conversa
entra no ramo quando o Jev classifica o público como `clt` e nenhuma jornada
INSS está em curso. Com a flag desligada, quem é CLT continua sendo atendido
pela FAQ, como antes.

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

## Testes

- `tests/test_clt_regras.py` e `tests/test_clt_mensagens.py`: sem rede nem banco.
- `tests/test_clt_jornada.py`: jornadas com Postgres, o simulador da Granatech em
  processo e uma BrasilAPI falsa. Sem `SATURDAY_TEST_DATABASE_URL`, esses testes
  são pulados.
