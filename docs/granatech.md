# Granatech (Fase 4)

Camada que fala com a API de parceiros da Granatech. O ramo CLT (Fase 5, ver
[`clt.md`](clt.md)) a usa até a oferta; a proposta com pós-venda entra na Fase 6. Os termos (consulta, vínculo, liberado, teto, cota,
reaproveitamento) estão no [`GLOSSARY.md`](../GLOSSARY.md).

## Onde está cada coisa

| Arquivo | O que faz |
| --- | --- |
| `apps/core/src/saturday/bancos/granatech/cliente.py` | HTTP, token, retry, consulta, simulação, proposta e reconciliação |
| `bancos/granatech/normalizacao.py` | Respostas da API → `DetalheConsulta`, `Vinculo`, `Produto`, `Simulacao`; corpo da proposta |
| `bancos/granatech/numeros.py` | `"1.500,00"`, `"1500.00"`, `"1.500"` e número do JSON → `Decimal` |
| `bancos/granatech/teto.py` | Nova parcela quando o liberado passa do teto |
| `bancos/granatech/status.py` | Ordem dos status, finais e regressões legítimas |
| `dados/cota.py` | Reserva e devolução de cota, com trava e alerta a 80% |
| `web/api/granatech.py` | `POST /webhooks/granatech` |
| `jobs/granatech.py` | Aplica os eventos no worker |
| `jobs/alertas.py` | Alerta de consulta sem evento há 15 min |
| `simuladores/granatech/app.py` | Simulador |

Não há interface `Banco` ainda: ver
[decisão 0004](decisoes/0004-sem-interface-banco-com-um-banco-so.md).

## Ligar

`SATURDAY_GRANATECH_ATIVO=true` monta o cliente no worker e exige
`SATURDAY_GRANATECH_CHAVE_API` e `SATURDAY_GRANATECH_WEBHOOK_TOKEN`. O webhook
fica no ar mesmo com a flag desligada: sem token ele responde 503 a tudo, e em
`homolog` e `prod` o serviço não sobe sem o token. A criação de proposta tem a
própria flag, `SATURDAY_GRANATECH_PROPOSTA_ATIVA`.

## Cliente

- **Token:** login em `POST /api/v1/auth/login`, guardado na memória de cada
  processo (API e worker têm o seu) e renovado 5 min antes de vencer. `expira_em`
  aceita `"1h"`, minutos, segundos ou data ISO; sem formato reconhecido, 1 h. Em
  401, renova e repete uma vez.
- **Retry:** GET repete uma vez em erro de rede ou 5xx, depois de 1,5 s. POST
  nunca repete. POST sem resposta (timeout, 5xx, conexão caída depois do envio)
  vira `ErroIncerto`; erro de conexão antes do envio é `ErroGranatech` comum.
- **Registro:** cada chamada grava em `chamadas_externas` só método, rota-modelo
  (`/consulta-saldo/{id}`), status e duração. A URL real nunca é gravada, porque
  a consulta leva CPF, nome e telefone na query string.

## Consulta e cota

`abrir_consulta(cpf, nome, telefone)` segue esta ordem:

1. procura na tabela `consultas_granatech` uma consulta do mesmo CPF criada nos
   últimos `SATURDAY_GRANATECH_REAPROVEITAR_DIAS` que não terminou em erro;
2. se não achar, procura na listagem por CPF da Granatech (só item com data
   dentro da janela);
3. se não achar, reserva cota (limite do dia e do mês, sob trava consultiva) e
   abre a consulta. Sem cota, levanta `CotaEsgotada` sem chamar a Granatech.

A reserva só é devolvida quando a Granatech recusa com um 4xx comprovado (por
exemplo, telefone inválido). Em timeout ou 5xx ela fica gasta: a consulta pode
ter sido aberta. Ao passar de 80% do mês, abre o alerta `cota_80`.

O detalhe da consulta não tem status: está pronto quando traz margens. Ele é
guardado em `consultas_granatech.detalhe` no formato da própria API, recortado
aos campos do contrato, e lido de volta pelo mesmo `normalizar_detalhe`.

## Simulação e teto

`simular_no_teto` simula e, se o liberado passar de
`SATURDAY_GRANATECH_TETO_LIBERADO`, calcula a nova parcela como
`floor(parcela × teto / liberado × folga × 100) / 100`. A folga é 1 na primeira
tentativa e `1 − 0,005 × (tentativa − 1)` nas seguintes. São no máximo 4 novas
simulações. Parcela abaixo de R$ 45 significa sem oferta (`None`). A simulação
devolvida diz `limitado_ao_teto` e `seguro_aplicado`; este último vem do bloco
que **voltou**, porque na dev `seguro=false` é ignorado.

## Proposta

`criar_proposta` grava a intenção em `propostas_granatech` antes do POST e:

- se a consulta já tem proposta criada, devolve a mesma, sem novo POST;
- se o POST é incerto, ou se uma intenção anterior ficou sem desfecho, procura na
  listagem por CPF a proposta da mesma consulta com a mesma parcela e o mesmo
  prazo, criada depois da intenção (com 5 min de folga de relógio);
- se não achar, levanta `ErroIncerto` e não tenta de novo: quem chama decide
  (na Fase 6, handoff).

## Webhook e worker

`POST /webhooks/granatech` aceita o token em `?t=`, `Authorization: Bearer` ou
`x-webhook-token`, comparado em tempo constante. O access log já corta a query
string. O evento vai para `eventos_recebidos` com o sha256 do JSON canônico como
id, então um reenvio idêntico é descartado.

O worker separa os eventos pela origem. Para a Granatech:

- localiza a consulta (`id_solicitacao`) ou a proposta (`id_proposta`) local;
- anota o evento no `historico`, sempre;
- aplica o status só se ele avança na jornada. Status final nunca muda.
  `REFAZER_SEGURANCA_IDENTIDADE` e `FALHA_PAGAMENTO` podem voltar etapas enquanto
  a proposta não é final. `PAGO` e `PROPOSTA_PAGA` valem `PAYED`;
- no `SUCCESS` da consulta, com o cliente ligado, busca e grava o detalhe. Se ele
  ainda vier sem margens, o evento volta para a fila;
- status desconhecido, id desconhecido e os status de consulta de significado
  pendente abrem o alerta `granatech_evento`, só com ids e status, sem CPF;
- com a consulta em status final, roda um turno de sistema na conversa
  (`consulta_pronta`, `consulta_sem_margem` ou `consulta_erro:<status>`, ver
  [`clt.md`](clt.md)).

Uma consulta não final sem nenhuma mudança há 15 min abre `consulta_parada`
(uma vez por consulta). Se ela ainda espera a autorização do cliente, a conversa
recebe o link do termo (`termo_pendente`). Fora isso não há polling: a reconciliação cobre só a
proposta incerta.

## Simulador

```bash
uv run --project simuladores uvicorn app:app --app-dir simuladores/granatech --port 8200
```

No compose local ele sobe como `granatech` na porta 8200, e a API e o worker já
apontam para ele. A chave padrão é `chave-do-simulador` e o token do webhook é
`token-do-simulador` (ou os valores do `.env`). Os dados são os da dev: CPF
`00189004967`, duas margens de R$ 1.500 (Prime Tech LTDA e EMPREGADOR MOCK
LTDA), produtos AA17, AA25, AAA36 e AAA48 a 4% a.m., e a simulação AAA36 36 ×
R$ 300 com liberado de R$ 4.619,53. Outras parcelas e prazos são escalados a
partir dela.

Admin:

| Rota | Corpo | Efeito |
| --- | --- | --- |
| `POST /admin/evento` | `{tipo, id, status, tipo_notificacao?, informacoes?, repetir?}` ou `{eventos: [...], ordem: "invertida"?}` | Envia o webhook ao Saturday |
| `POST /admin/falha` | `{rota, status: 401\|500\|"timeout", vezes?, metodo?, registrar?}` | As próximas chamadas daquela rota exata falham; com `registrar`, a operação acontece antes (POST incerto) |
| `POST /admin/config` | `{atraso_detalhe_s?, expira_em?, timeout_s?}` | Ajusta o simulador |
| `POST /admin/limpar` | — | Zera o estado |
| `GET /admin/estado` | — | Consultas, propostas, logins e chamadas |

O `SUCCESS` disparado pelo admin deixa o detalhe da consulta pronto na hora. Sem
ele, o detalhe fica pronto `atraso_detalhe_s` depois do termo (8 s por padrão).

Nos testes do core, o simulador roda em processo pelo `TestClient`
(`tests/conftest.py`, fixtures `simulador_granatech` e `http_granatech`).

## Pendências com a Granatech

Cada uma está no código como `TODO(granatech)`:

- qual parâmetro da listagem por CPF vale, `filterBy` ou `filtrar_por` (vão os
  dois);
- formato das listagens de consulta e de proposta (aceitamos lista ou `data`,
  `dados`, `items`, `content`);
- formato da resposta do `POST /propostas` (aceitamos `id`, `id_proposta` ou
  `data.id`);
- `informacaoDeSeguros` de proposta sem seguro;
- `tipo_empregador` (padrão 1, por configuração);
- significado de `FIDUCIARY_INSTITUTION_NO_AUTHORIZATION` e
  `WORKER_MUST_CANCEL_RETURN_REQUEST` (por ora, alerta);
- corpo do `PATCH /propostas/{id}/dados-bancarios` (fora desta fase).
