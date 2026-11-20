# Granatech (Fase 4)

Camada que fala com a API de parceiros da Granatech. O ramo CLT (fases 5 e 6,
ver [`clt.md`](clt.md)) a usa da consulta ao pagamento. Os termos (consulta, vínculo, liberado, teto, cota,
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

A intenção guarda também a simulação que o cliente aceitou (`condicoes`), para o
painel mostrar liberado, taxa, CET e seguro da proposta mesmo depois que a
conversa seguir; a reconciliação não as sobrescreve. Propostas anteriores a
isso ficam com `condicoes` nula e o painel usa a oferta do checkpoint.

## Webhook e worker

`POST /webhooks/granatech` aceita o token em `?t=`, `Authorization: Bearer` ou
`x-webhook-token`, comparado em tempo constante. O access log já corta a query
string. O evento vai para `eventos_recebidos` com o sha256 do JSON canônico como
id, então um reenvio idêntico é descartado.

O evento de consulta da api-dev chega como `{cpf, id_consulta, status, tipo}`,
não com o `id_solicitacao` da especificação (webhook recebido no dev em
2026-11-13); o worker e a homologação aceitam os dois nomes.

Chamada recusada (401) gera o log `granatech_token_invalido` com o diagnóstico,
nunca o token: `token_fontes` (por onde veio: `authorization_bearer`,
`authorization_sem_bearer:cru` para token sem o prefixo `Bearer `,
`x-webhook-token`, `query_t` ou `nenhuma`), tamanho e `token_impressao` (8 hex
do SHA-256) do recebido e do esperado, `token_com_espacos`,
`token_bate_sem_espacos`, `authorization_cru_bate` (o token certo, só que sem
`Bearer `), nomes dos cabeçalhos e dos parâmetros, `user_agent`, tamanho e
chaves do corpo e o `tipo`. Impressões iguais = mesmo token; diferentes = a
Granatech tem outro token cadastrado.

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

Fora da API real: `cenario` na query de `GET /consulta-saldo`, mandado só pelo
cliente de teste do Saturday (decisão 0024). Com `sucesso`, `sem_margem` ou
`erro`, o simulador envia sozinho o webhook `SUCCESS`, `NO_MARGIN` ou
`UNEXPECTED_ERROR`, `atraso_detalhe_s` depois do termo. Com `termo_pendente`, o
termo responde 400 e nenhum evento sai. Com `sem_nascimento`, `sem_mae` ou
`sem_endereco` (cliente sem dados, como os CPFs da api-dev), a consulta dá
`SUCCESS`, mas a `pessoa_natural` do detalhe vem sem `birth_date`,
`mother_name` ou `address`.

Nos testes do core, o simulador roda em processo pelo `TestClient`
(`tests/conftest.py`, fixtures `simulador_granatech` e `http_granatech`).

## Aba Granatech do painel

A tela `/granatech` do painel ([decisão 0013](decisoes/0013-acoes-do-painel-na-granatech-por-turno-de-sistema.md))
lista consultas e propostas (filtro por status, período e CPF completo; CPF
mascarado, revelar com auditoria), mostra o detalhe com vínculos, linha do
tempo do `historico` e a cota, e se atualiza pelo SSE (aviso `granatech`).
Atendente e gestor veem; só o gestor age, e cada ação grava a auditoria antes
de chamar o banco. A API fica em `web/api/granatech_admin.py`
(`/admin/granatech/*`), e quem decide se uma ação cabe é
`acoes_da_consulta`/`acoes_da_proposta`. Em cada proposta ou consulta roda uma
ação por vez: a segunda recebe 409, e o link de biometria só é reenviado de
novo depois de 1 minuto ([decisão 0025](decisoes/0025-uma-acao-do-gestor-por-vez.md)).

| Ação | O que faz |
| --- | --- |
| Reconciliar | Proposta com envio `incerta`: procura na listagem. Achada, devolve a conversa à IA e roda o turno `painel:reconciliar`, que segue do aceite sem novo POST (dados do tomador e aviso). Não achada, nada muda |
| Reenviar link | Proposta em formalização: turno `proposta:formalizar`/`refazer` com `forcar=True`, que fala com o cliente mesmo com a conversa com humano |
| Cancelar | `POST /propostas/{id}/cancelar` com motivo na auditoria; o cliente é avisado quando o webhook `CANCELED` chegar |
| Corrigir conta | Só com `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO` e a proposta em `PENDING_USER_REVIEW`; banco da lista `GET /bancos`; a auditoria guarda só o banco e os 2 últimos dígitos |
| Atualizar detalhe | Consulta sem detalhe: relê o `GET /consulta-saldo/{id}`; com margens, marca `SUCCESS` e roda `consulta_pronta` |

Abrir consulta, simular e criar proposta não existem no painel: dependem do SIM
do cliente. Item sem conversa fica só para leitura.

## Integração (APP MEX)

O Saturday é proxy da Granatech para o APP MEX ([decisão 0035](decisoes/0035-api-granatech-para-o-app-mex.md)):
o APP MEX fala no formato da Granatech, e o Saturday troca o token da
integração pelo login da MEX. Triagem e consentimento pela integração são do
APP MEX ([decisão 0036](decisoes/0036-consentimento-e-triagem-pela-integracao.md));
cota e teto continuam do Saturday.

- **Tokens:** página Integrações do painel, só gestor
  (`/admin/gestao/integracoes`). O token (`sat_...`) aparece uma vez; o banco
  guarda o sha256. Escopos: `leitura`, `revelar`, `acoes`, `operacoes`,
  `homologacao`. Criar e revogar vão para a auditoria.
- **Chamada:** `Authorization: Bearer sat_...`. Sem token ou revogado: 401; sem
  o escopo: 403; Granatech desligada: 503; falha de rede ou 5xx dela: 502.
- **Proxy (fase 1, só leitura, escopo `leitura`)**, em
  `/integracao/granatech/api-consignado/v1/`: `GET consulta-saldo/usuario`,
  `GET consulta-saldo/{id}`, `GET bancos`, `GET propostas/lista`,
  `GET propostas/{id}`. Query string e corpo passam crus, menos o CPF (chaves
  com "cpf" no nome e `document`/`documento`), que sai mascarado; a recusa da Granatech
  (4xx) volta com o status e o corpo dela (`null` se ela não mandou JSON),
  menos 401 e 403, que são do login da MEX e viram 502. Rota fora da lista: 404;
  id no caminho fora de `[A-Za-z0-9_-]`: 422.
- **Rotas do Saturday:** `GET /integracao/cota` (`leitura`) e
  `POST /integracao/consultas/{id_da_granatech}/revelar` (`revelar`, auditado
  sem usuário e com `origem: integracao`).
- **Webhook de saída (fase 2):** cada integração pode ter um endereço
  (`https://`; `http://localhost` fora de homolog e prod) e um segredo
  (`whsec_...`, mostrado uma vez; trocar invalida o anterior), cadastrados na
  página Integrações (`PUT /admin/gestao/integracoes/{id}/webhook`,
  `POST .../webhook/segredo`, `GET .../webhook/entregas`). Quando um evento da
  Granatech muda o status de uma consulta ou proposta com `integracao_id`, o
  worker grava no outbox (canal `integracao`, mesma transação do status) e
  entrega `POST` com o corpo `{"tipo": "consulta"|"proposta", "evento": <evento
  da Granatech, CPF mascarado>, "recebido_em": ...}`. Status repetido ou
  regressão não avisa; o "atualizar detalhe" do painel também avisa, com
  `{"id_consulta", "status", "origem": "painel"}` no lugar do evento. Sem
  segredo gerado, nada entra na fila. 2xx é entregue; o resto tenta de novo com
  o backoff do outbox (timeout de 3 s, e a integração que falhou fica 1 minuto
  sem ser chamada, para não segurar o worker) e, no teto, desiste com o alerta
  `integracao_webhook_falhou`, um aberto por integração. Integração revogada ou
  sem endereço desiste sem chamar e sem alerta. O segredo fica em claro no
  banco, porque assina o corpo.
- **Repetição e ordem:** um 2xx perdido no caminho faz o aviso sair de novo. O
  cabeçalho `X-Saturday-Entrega` traz o id da entrega: o APP MEX descarta o que
  já viu. Avisos podem chegar fora de ordem (um que falhou volta depois do
  seguinte); aplique pelo status, sem regredir, ou por `recebido_em`.
- **Conferir a assinatura** (lado do APP MEX), igual ao webhook do `/chat`:

  ```python
  import hashlib, hmac

  def assinatura_valida(segredo: str, timestamp: str, corpo: bytes, recebida: str) -> bool:
      esperada = hmac.new(segredo.encode(), f"{timestamp}.".encode() + corpo, hashlib.sha256)
      return hmac.compare_digest(f"sha256={esperada.hexdigest()}", recebida)
  ```

  Com `timestamp = X-Saturday-Timestamp`, `recebida = X-Saturday-Signature` e o
  corpo cru, antes de ler o JSON. Recuse timestamp com mais de 5 minutos.
- **Escrita (fase 3)**, no mesmo prefixo. Item de outra integração ou de
  conversa do agente: 409. As respostas da Granatech voltam cruas (CPF
  mascarado; 401/403 dela viram 502).

  | Rota | Escopo | O que o Saturday confere |
  | --- | --- | --- |
  | `GET consulta-saldo?cpf&nome&telefone` | `operacoes` | Reaproveita a consulta recente do CPF sem gastar cota (`reaproveitada: true`); senão reserva cota (sem cota: 429) e abre. A consulta fica com a integração dona. Recente de outro dono: 409. Resposta: `{id, status, link_termo_consentimento, reaproveitada}`. |
  | `POST termo-consentimento` | `operacoes` | `id_consulta` da integração. |
  | `GET simulacao/{id_produto}` | `operacoes` | Liberado de algum bloco acima do teto: 422, sem a simulação. As outras ficam guardadas por 24 h. |
  | `POST propostas` | `operacoes` | Só com `SATURDAY_GRANATECH_PROPOSTA_ATIVA` (503). `id_consulta` da integração; `informacoesFinanceira[0]` repete uma simulação guardada (`id_produto`, `id_margem`, `numero_parcelas`, `valor_parcela`, `valor_solicitado`) e está no teto (422). Intenção gravada antes, sem retry. Resposta `{id, reaproveitada}`; repetir devolve a mesma, sem novo POST. Incerta: 202 `{situacao: "incerta", ...}` — consulte `propostas/lista` antes de repetir. |
  | `POST propostas/{id}/dados-tomador` | `operacoes` | Proposta da integração. |
  | `POST propostas/{id}/cancelar` | `acoes` | Proposta da integração. |
  | `PATCH propostas/{id}/dados-bancarios` | `acoes` | Proposta da integração e `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO` (503). |

- **A fazer:** homologação pela integração (fase 4).

## Pendências com a Granatech

Cada uma está no código como `TODO(granatech)`:

- nomes em português dos status de consulta: a api-dev manda o webhook em
  português e o PDF "Consultas-Webhook" (reenviado em 2026-11-19) só traz os
  sete em inglês. Só `AGUARDANDO_AUTORIZACAO_DO_CLIENTE`, `CONCLUIDO` e
  `ERRO_INESPERADO` (este visto na produção em 2026-11-19) são traduzidos;
  faltam os de `PENDING`, `PROCESSING`, `NO_MARGIN` e `USED`. Outro nome vira
  alerta.

### Respondidas em 2026-11-19

- **Listagens** (`consulta-saldo/usuario` e `propostas/lista`): objeto paginado
  `{total, pagina_atual, tamanho_pagina, total_paginas, pagina_anterior,
  proxima_pagina, itens}`; lemos `itens`. O `GET /bancos` segue em lista pura.
- **`POST /propostas`:** o 201 traz só o id, como texto JSON, também em
  produção.
- **Webhook de proposta:** produção manda igual à homologação,
  `{tipo: "PROPOSTA", status, id_proposta, cpf}`, com o nome da notificação em
  `status`.
- **`GET /propostas/{id}`:** o status vem na propriedade `status`. O painel
  ainda não tem "atualizar status" (decisão 0013).
- **`FIDUCIARY_INSTITUTION_NO_AUTHORIZATION` e
  `WORKER_MUST_CANCEL_RETURN_REQUEST`:** são do FGTS, não do consignado; saíram
  do código. Se chegarem, viram alerta de status desconhecido.
- **`estado_civil`:** `SOLTEIRO`, `CASADO`, `DIVORCIADO`, `SEPARADO` e
  `VIUVO`. "União estável" (e "amasiado", "moro junto") grava `SOLTEIRO`.
- **Dados do tomador:** na maioria dos casos a consulta traz nascimento, mãe e
  endereço; se faltar, podemos preencher. A mãe e o endereço que faltarem o
  cliente informa na conversa (decisão 0034).

### Respondidas em 2026-11-16

- **Filtro da listagem por CPF:** `filtrar_por`; o `filterBy` do Swagger saiu.
- **`informacaoDeSeguros.id_externo`:** vai só o número (o
  `id_cobertura_seguro`, decisão 0015); a Granatech troca o valor sozinha
  depois dos dados do tomador, quando o seguro é contratado.
- **Proposta sem seguro:** vai sem o bloco `informacaoDeSeguros`. Na
  homologação todo produto tem seguro; o produto sem seguro só aparece em
  produção, quando a margem do tomador se enquadra nele.
- **`tipo_empregador`:** 1 = CNPJ, 2 = CPF. Sai do `documento_empregador` do
  vínculo (11 dígitos, 2; senão, 1).
- **`PATCH /propostas/{id}/dados-bancarios`:** mesmo `banco_detalhe` dos dados
  do tomador, e só com a proposta em `PENDING_USER_REVIEW`. Continua atrás de
  `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO` (desligada por padrão): o PATCH
  ainda não rodou contra a api-dev.
- **Termo de consentimento:** a assinatura pela API
  (`POST termo-consentimento`) basta em produção; o link só vai ao cliente se
  a assinatura falhar.

## Homologação com a Granatech

O material recebido da Granatech está em
[`granatech-homologacao/`](granatech-homologacao/README.md), sem segredos. A
homologação tem duas fases (`roteiro-homologacao.md`):

- **Fase 1, consultas e simulações** (aprovada em 2026-11-11): 2 consultas (uma
  pela resposta direta, outra pelo webhook) e 2 simulações (com e sem seguro).
- **Fase 2, contratação:** 2 contratações com sucesso, com o status recebido
  pelo webhook, e 1 erro de contratação.

As evidências saem da seção **Homologação** da aba Granatech do painel
([decisão 0014](decisoes/0014-homologacao-pelo-painel.md)). Só o gestor vê a
seção, e só fora de produção: com `SATURDAY_ENVIRONMENT=prod` ou com a base em
`api.granatech.com.br` ela some e a API responde 404.

1. O gestor clica em "Gerar Fase 1" ou "Gerar Fase 2" e confirma; a rodada
   fica `pendente` (uma por vez, auditada).
2. O worker pega a rodada e a roda numa thread própria, com a
   `SATURDAY_GRANATECH_CHAVE_API` do ambiente: abre a consulta (1 na Fase 1, 2
   na Fase 2), espera as margens e os webhooks (até 10 min cada, lidos direto
   de `eventos_recebidos`) e grava cada chamada como evidência.
3. A tela mostra os itens (ok ou falhou) e o JSON de cada passo, ao vivo pelo
   SSE; no fim, "Baixar .zip" traz um JSON por passo e o `RELATORIO.md`.

Os webhooks só chegam ao deploy cadastrado na Granatech: hoje o homolog
(`https://saturday-homolog.dynatech.systems/webhooks/granatech`, header
`x-webhook-token`; até 2026-11-11 ia para `granatech.dynatech.systems`, o
serviço antigo). Em outro ambiente o item "via webhook" falha; a seção mostra a
URL que o ambiente espera. As consultas e propostas da homologação não entram
nas listas da aba nem na cota, e o webhook delas não abre alerta.

A chave e o token nunca são gravados. Se o worker reiniciar no meio, a rodada
fica `interrompida`; gere outra. Na dev, o pedido "sem seguro" é ignorado e
volta o bloco com seguro; a evidência da simulação sem seguro registra isso.
