# iCred

## Como está hoje (fase 1)

Só com `SATURDAY_ICRED_ATIVO=true`; sem ela o ramo INSS é o de antes. As
decisões estão em `docs/decisoes/0027-icred-pelo-motor-da-mex.md`.

1. O cliente manda o extrato. Depois do cálculo da portabilidade (com contrato
   elegível ou com `sem_portabilidade`), o nó `icred_porta` pede o SIM para
   consultar o iCred, uma vez por conversa. Conversa sem telefone não é
   consultada.
2. SIM: o agente pede o CPF (o ramo INSS não o tem). Com o CPF válido, grava a
   prova `icred_consulta` e abre a consulta (`acao: consultar`,
   `Idempotency-Key`). Só "sim", "autorizo" ou "aceito" valem como SIM, aqui e
   no aceite. NÃO, duas respostas que não são sim nem não, CPF inválido duas
   vezes, motor fora do ar ou CPF com consulta aberta em outra conversa: a
   conversa segue o caminho de antes.
3. O resultado chega pelo webhook `consulta.concluida` e vira um turno de
   sistema. `agent/icred/regras.py` decide:
   - `JA_GRAVADO`, `PROPOSTA_EXISTENTE`, `TELEFONE_VINCULADO`: handoff
     `icred_bloqueio`;
   - algum contrato acima de 1,85% ao mês: handoff `icred_taxa_alta`;
   - oferta que não deu para ler inteira: handoff `icred_conferir`;
   - sem oferta, ou total na conta menor ou igual ao da portabilidade C6: o
     caminho de antes;
   - senão, a oferta do pacote inteiro.
4. Aceite: prova `icred_aceite` e handoff `icred_aceite`, com os contratos e se
   a consulta já venceu no detalhe do alerta. O atendente grava pelo painel do
   motor.
5. Sem resposta em `SATURDAY_ICRED_ESPERA_MIN` (5): o worker lê a consulta por
   id; continuando parada, a conversa segue o caminho de antes e abre o alerta
   `icred_consulta_parada`.

O agente nunca chama `/gravar`, `acao: gravar` nem `aceitar_mudanca`. A comissão
é descartada em `bancos/icred/normalizacao.py`. A oferta não cita seguro
(`TODO(icred)` em `agent/icred/textos.py`).

Testes em `apps/core/tests/test_icred.py`, contra `simuladores/icred/`. No
compose local o simulador sobe na porta 8400 e conclui a consulta sozinho com
`SIMULADOR_ICRED_CENARIO`.

## Pesquisa da especificação

> **O que segue é a pesquisa de antes da implementação.** Lido em 2026-11-16.
> O que foi decidido está na decisão 0027. Onde a especificação e o código-fonte
> do motor divergem, vale a última seção
> ([O que o código-fonte do motor respondeu](#o-que-o-código-fonte-do-motor-respondeu)).
>
> - Especificação: `https://api-icred.dynatech.systems/openapi.json` (apontada por
>   `url: '/openapi.json'` na página `https://api-icred.dynatech.systems/docs`).
> - Título `iCred — motor de consultas`, `info.version` **1.1.0**, OpenAPI 3.1.0,
>   93.622 bytes, 30 operações, 38 schemas, 7 webhooks.
> - Só foram feitos dois GET públicos (a página e o JSON). Nenhuma rota de negócio
>   foi chamada, nem `GET /situacoes` (exige chave).
> - A especificação não tem `servers`, `externalDocs`, `contact` nem
>   `termsOfService`: não há outra documentação oficial linkada.
>
> Cada afirmação traz a fonte: rota ou schema da especificação, ou `arquivo:linha`
> do repositório. O que é dedução minha está marcado como **inferência**.

## O que pesa na decisão

1. **Não é CLT.** A descrição diz "consulta e gravação de propostas **INSS**"
   (`info.description`). Os tipos de produto são `port`, `port_refin`, `refin` e
   `novo` (`ConsultaNova.produtos`). Não há Crédito do Trabalhador, FGTS nem
   outro produto. O equivalente no Saturday é o ramo INSS, não `agent/clt/`.
2. **Não é a API do banco.** É um motor que opera o iCred por logins de
   operador: "O supervisor abre o Chrome do login" (`POST /logins/{login}/iniciar`),
   "O Chrome do motor só deixa passar o reenvio" (`POST /reenvios`), "o mesmo que
   o botão … do iCred" (`POST /reenvios`, `POST /links`). **Inferência:** é
   automação de navegador sobre o portal do iCred; a especificação não usa esse
   termo nem diz quem mantém o motor.
3. **O motor escolhe o produto.** "o motor escolhe a tabela de **maior
   comissão**" (`info.description`). Quem integra só liga ou desliga tipos; não
   escolhe prazo, parcela, valor nem tabela.
4. **Consentimento é um booleano.** `lgpd_ok: true` declarado por quem chama
   (`ConsultaNova.lgpd_ok`). A API não coleta termo nem guarda prova. A
   assinatura é do iCred: "o iCred envia o link de assinatura ao cliente por
   WhatsApp/SMS".
5. **Webhook assinado com HMAC e fila de eventos consultável** (`GET /eventos`).
   É melhor que o da Granatech (token fixo).
6. **Gravação sem chave de idempotência documentada**, mas com consulta por id
   para conferir e a garantia "um CPF é gravado uma vez" (`info.description`).
7. **Não há status de proposta depois da assinatura** em nenhum schema: nem
   pago, nem cancelado. Só contagens (`propostas`, `link_enviado`) e
   `beneficio_bloqueado`.
8. **Não há ambiente de teste documentado.**
9. O host é `dynatech.systems`, o mesmo domínio do deploy do Saturday
   (`docs/granatech.md:251`), e o fluxo principal se chama "Maria/JEV". Ver a
   regra 1 em [Conflitos](#conflitos-com-o-agentsmd).

## Visão geral

| Item | O que a especificação diz | Fonte |
| --- | --- | --- |
| Base URL | Não declarada (sem `servers`). **Inferência:** a origem da página, `https://api-icred.dynatech.systems` | raiz do JSON |
| Ambientes | Não documentado. Não há homologação, sandbox nem produção nomeados | — |
| Versão | 1.1.0; `GET /saude` também devolve `versao` | `info.version`, `Saude` |
| Produtos | INSS: portabilidade, portabilidade + refinanciamento, refinanciamento, empréstimo novo | `ConsultaNova.produtos` |
| Tempo | "~40 s por cliente, mais a fila" | `POST /consultas` |
| Formato de erro | `{"erro": {"codigo", "mensagem", "detalhes"}}` | `Erro`, `ErroDetalhe` |
| Corpo máximo | 64 KB (`413 corpo_grande`) | `POST /consultas` |

`GET /saude` traz `portabilidade_pausada`: com `ICRED_PAUSAR_PORTABILIDADE=1`
no servidor, "Port + Refin fora do plano e da gravação (só Novo e Refin)"
(`Saude`). Ou seja, o conjunto de produtos muda por configuração do lado deles.

## Autenticação

- Esquema único: `APIKeyHeader`, cabeçalho **`X-API-Key`**, "cada aplicação tem
  a sua" (`components.securitySchemes`).
- Só `GET /saude` dispensa a chave.
- **Escopos** por chave, citados nas tags: `consultas`, `consultas:gravar`,
  `planilhas`, `operacao`. Existe um papel "admin" que vê outras aplicações
  (`GET /consultas/{cid}`, `GET /eventos`).
- `GET /eu` devolve `aplicacao`, `escopos`, `descricao_escopos`,
  `limite_por_minuto` e `limite_gravacoes_dia` (`Eu`).
- Não documentado: como a chave é emitida, se expira, como se troca. Não há
  token, login nem renovação.

## Rotas

Todas (menos `/saude`) documentam `401 chave_invalida`, `422 dados_invalidos` e
`429 limite_requisicoes`. As com escopo documentam também `403 sem_permissao`. A
tabela lista só os códigos além desses.

### sistema

| Rota | Finalidade | Resposta | Erros a mais |
| --- | --- | --- | --- |
| `GET /saude` | Saúde, sem chave | `Saude {status, versao, portabilidade_pausada}` | — |
| `GET /situacoes` | Dicionário `situacao → explicação` | objeto `{chave: texto}` | — |
| `GET /eu` | Aplicação, escopos e limites da chave | `Eu` | — |

### consultas (escopo `consultas`; gravar e reenviar exigem `consultas:gravar`)

| Rota | Finalidade | Corpo obrigatório | Resposta | Erros a mais |
| --- | --- | --- | --- | --- |
| `POST /consultas` | Põe o cliente na fila. `acao=consultar` simula; `acao=gravar` simula e grava | `cpf`, `telefone`, `lgpd_ok`. Opcionais: `nome`, `acao` (padrão `consultar`), `referencia`, `callback_url`, `produtos`. Cabeçalho opcional `Idempotency-Key` (até 100) | `202 Aceito {id, estado, posicao_na_fila, ja_existia}` | 403, 413, `429 limite_gravacoes` |
| `GET /consultas` | Lista, mais recentes primeiro. Filtros `referencia`, `cpf`, `limite` (1–500, padrão 50) | — | `Consulta[]` | 403 |
| `POST /consultas/lote` | Até 200 consultas; cada item validado sozinho | `itens`. Opcionais: `acao`, `produtos`, `callback_url`, `referencia_lote`. `Idempotency-Key` (até 90) | `207 ConsultasLoteResposta {aceitos, recusados, itens[]}` | 403, 413 |
| `GET /consultas/{cid}` | Uma consulta, "mesmo formato do `dados` do evento" | — | `Consulta` | 403, 404 |
| `POST /consultas/{cid}/gravar` | Grava consulta `COM_OFERTA` dentro de `valido_ate` | Corpo opcional `GravarPedido {produtos, aceitar_mudanca, vencida_ok}` | `202 Aceito` | 403, 404, `409 nao_gravavel`, `409 consulta_vencida` |
| `POST /consultas/{cid}/cancelar` | Cancela só enquanto `estado = na_fila`. "Não cancela nada no iCred" | — | `200 Aceito` | 403, 404, `409 nao_cancelavel` |
| `POST /reenvios` | Reenvia o link de assinatura das propostas aguardando assinatura | `cpf`, `confirmacao: "REENVIAR"`. Opcionais: `telefone`, `proposta` (uuid), `login` | `202 Reenvio` | 403, 409, `429 reenvio_recente`, `429 limite_reenvios` |
| `GET /reenvios/{rid}` | Resultado do reenvio | — | `Reenvio {estado, situacao, propostas[]}` | 403, 404 |
| `POST /links` | Recupera o link atual de até 500 CPFs. "Só leitura" | `cpfs`. Opcional `login` | `202 Links` | 403 |
| `GET /links/{lid}` | Resultado da busca | — | `Links {estado, total, prontos, resultados[]}` | 403, 404 |

### lote (escopo `planilhas`)

| Rota | Finalidade | Corpo obrigatório | Resposta | Erros a mais |
| --- | --- | --- | --- | --- |
| `GET /planilhas` | Planilhas e lotes JSON importados | — | `PlanilhaImportada[]` | 403 |
| `POST /planilhas` | Envia `.xlsx` ou `.csv` | `multipart/form-data`, campo `arquivo` | `201 Importacao` | 403, 413, 415 |
| `POST /lote/clientes` | Até 10.000 clientes em JSON | `clientes[]` com `cpf`, `lgpd_ok` | `201 ImportacaoJson` | 403, 413 |

### eventos (qualquer chave)

| Rota | Finalidade | Resposta |
| --- | --- | --- |
| `GET /eventos` | Eventos da aplicação, do mais antigo ao mais novo. Filtros `desde` (`^e_[0-9a-f]+$`), `tipo`, `limite` (1–1000, padrão 100), `aplicacao` (só admin) | `Evento[]` com `entrega {estado, tentativas, erro}` |
| `POST /eventos/teste` | Cria um `teste.ping` para o `webhook_url` | `202 TesteWebhook {evento_id, url, estado}` |

### operação (escopo `operacao`)

Todas respondem `200`/`202` com schema **vazio** (`{}`): a forma da resposta só
existe em prosa na descrição.

| Rota | Finalidade |
| --- | --- |
| `GET /logins` | Estado de cada login (desejado, real, sinal de vida, tarefa) |
| `POST /logins/{login}/iniciar`, `POST /logins/{login}/parar` | Liga e para o worker do login |
| `PUT /logins/{login}/lote`, `PUT /lote` | `LoteComando {modo: parado\|a_seco\|gravar, limite, confirmacao}`; `gravar` exige `confirmacao: "GRAVAR"` |
| `GET /fila` | Contagens do lote e das consultas, com comissão estimada |
| `GET /clientes/{cpf}` | Histórico do CPF "nas consultas de **todas as aplicações**" |
| `GET /gravados` | Uma linha por CPF com propostas da última conferência e `acao` (`enviar_link`, `desbloqueio`, `cancelada`, `andamento`, `concluida`, `conferir`, `verificar`). Filtros `acao`, `login`, `busca`, `origem`, `pagina`, `por_pagina` |
| `GET /gravacoes/andamento` | Fila de gravações por login |
| `POST /conferencias`, `GET /conferencias/{grupo}` | Confere se o link foi enviado e se o benefício está bloqueado. `ConferenciaPedido {dia, rodada, tudo, ofertas, cpfs}` |
| `GET /exportacoes` | Planilha `.xlsx` dos gravados com comissão |

## Jornada (INSS, a única que existe)

Fluxo "Maria/JEV (decidir antes de gravar)" de `info.description`:

1. **Consentimento.** Quem chama envia `lgpd_ok: true`: "o cliente autorizou o
   uso dos dados (LGPD)" (`ConsultaNova.lgpd_ok`). "Só grava com `lgpd_ok =
   true`" (`info.description`). Não há termo, link, biometria nem prova do lado
   da API. Quem coleta e guarda a prova é o integrador.
2. **Consulta e simulação, juntas.** `POST /consultas` com `acao: consultar` →
   `202` com `id`. Não há rota separada de margem ou elegibilidade.
3. **Resultado.** Evento `consulta.concluida` (ou `GET /consultas/{id}`) com
   `Consulta`: `estado` (`na_fila`, `processando`, `concluida`, `cancelada`),
   `situacao`, `detalhe`, `produtos[]`, `valido_ate`, `comissao_rs`. Cada
   `Produto` tem `produto`, `tipo`, `banco`, `tabela`, `taxa` (% ao mês),
   `prazo`, `parcela`, `liberado`, `bruto`, `saldo_devedor`, `rest`, `regra`,
   `pct` e `comissao`. Todos os campos de `Produto` são opcionais.
4. **Gravação (a proposta).** `POST /consultas/{id}/gravar` até `valido_ate`. "O
   motor relê o lead e só grava se as ofertas forem as mesmas; senão a consulta
   termina em `RECALCULO`". Opções: `produtos` (restringe tipos; sem oferta
   deles, `SEM_PRODUTO_PERMITIDO`), `aceitar_mudanca` (grava as ofertas atuais
   mesmo diferentes, e devolve `oferta_mudou` e `liberado_antes`) e `vencida_ok`
   (grava depois do prazo, só se as ofertas forem idênticas). O resultado é um
   novo `consulta.concluida`.
5. **Formalização.** "o iCred envia o link de assinatura ao cliente por
   WhatsApp/SMS" para o `telefone` da consulta. `link_cliente` tem o formato
   `https://minha.icred.digital/resume/<lead_uuid>` (`Consulta.link_cliente`). O
   que o cliente faz nesse link (dados, documentos, biometria) não está
   documentado.
6. **Acompanhamento.** `consulta.link_atualizado` quando "a conferência viu
   mudança em `propostas`, `link_enviado` ou bloqueio do benefício". A
   conferência é pedida por `POST /conferencias` (escopo `operacao`). O status
   de cada proposta só aparece em `GET /gravados`, em prosa ("status e evento em
   português") e sem schema.
7. **Cancelamento.** Não existe. "nunca cancela proposta"
   (`info.description`). `POST /consultas/{cid}/cancelar` só tira da fila.

Valores de `situacao` citados na especificação: `COM_OFERTA`, `GRAVADO`,
`RECALCULO`, `SEM_PRODUTO_PERMITIDO`, `A_SECO_COM_OFERTA` (só no lote a seco).
A lista completa só existe em tempo de execução, em `GET /situacoes`.
`Consulta.etapa` e `Consulta.acao` são texto sem enum.

O atalho `acao: gravar` em `POST /consultas` grava sem ninguém ver a oferta.

## Webhooks

A especificação tem a seção `webhooks` (OpenAPI 3.1).

| Evento | Quando | `dados` |
| --- | --- | --- |
| `consulta.concluida` | Consulta terminou; de novo depois de `/gravar` | `Consulta` |
| `consulta.link_atualizado` | Conferência viu link enviado ou benefício bloqueado | `Consulta` |
| `lote.cliente_processado`, `lote.link_atualizado` | O mesmo, para cliente de lote | `ClienteLoteEvento` |
| `reenvio.concluido` | `POST /reenvios` terminou | objeto livre `{id, login, cpf, situacao, detalhe, propostas}` |
| `links.concluido` | `POST /links` terminou num login | objeto livre `{id, login, resultados[]}` |
| `teste.ping` | `POST /eventos/teste` | objeto livre |

- **Envelope:** `{id, evento, criado_em, dados}` (`Evento`).
- **Destino:** `callback_url` do pedido → `webhook_url` da aplicação → só em
  `GET /eventos`.
- **Cabeçalhos:** `X-Icred-Evento`, `X-Icred-Id`, `X-Icred-Timestamp` (segundos
  UTC), `X-Icred-Assinatura`.
- **Assinatura:** `sha256=HMAC-SHA256(segredo_webhook, "<timestamp>.<corpo
  bruto>")`. "Recuse timestamp com mais de 5 minutos."
- **Reentrega:** espera `2xx` em até 10 s; senão tenta de novo em 30 s, 2 min,
  10 min, 30 min e 1 h. `X-Icred-Id` serve para descartar repetidos.
- **Recuperação:** `GET /eventos?desde=<último id>`; `entrega.estado` é
  `pendente`, `enviado`, `falhou` ou `sem_webhook`.

**Status de proposta e finais:** não documentado. Não há enum de status de
proposta. `ReenvioProposta.resultado` (`REENVIADO`, `TELEFONE_VINCULADO`,
`ERRO`) é o resultado do reenvio, não o status da proposta.

Duas incoerências do próprio texto: "nunca reenvia link" (`info.description`)
convive com `POST /reenvios`; e `Evento.evento` lista cinco tipos, sem
`reenvio.concluido` e `links.concluido`.

## Idempotência e conferência depois de timeout

| Operação | O que há | Fonte |
| --- | --- | --- |
| `POST /consultas` | `Idempotency-Key`; e, sem ela, "se o mesmo CPF já estiver na fila ou processando para esta aplicação, devolve a consulta existente (`ja_existia=true`)" | descrição da rota |
| `POST /consultas/lote` | `Idempotency-Key`: "o reenvio do mesmo lote não cria nada de novo" | descrição da rota |
| `POST /consultas/{cid}/gravar` | **Sem** `Idempotency-Key` nos parâmetros. Segunda chamada: `409 nao_gravavel` quando a situação não é `COM_OFERTA` | parâmetros e descrição |
| Garantia geral | "um CPF é gravado uma vez" | `info.description` |
| Conferir depois | `GET /consultas/{cid}`, `GET /consultas?referencia=`, `GET /eventos?desde=` | rotas |

Para a regra 4: dá para gravar a intenção, fazer um POST só e, no resultado
incerto, ler `GET /consultas/{cid}` antes de qualquer coisa. O que a
especificação não diz é o que responde um segundo `/gravar` enquanto o primeiro
ainda está na fila (pergunta 9).

## Limites

| Limite | Valor | Fonte |
| --- | --- | --- |
| Requisições por minuto | Por aplicação, em `Eu.limite_por_minuto`. O exemplo de erro cita 60 | `Eu`, exemplo do 429 |
| Gravações por dia | `Eu.limite_gravacoes_dia` (pode ser nulo); `429 limite_gravacoes` | `Eu`, `POST /consultas` |
| Reenvio | Um por CPF a cada 6 h; limite diário por aplicação | `POST /reenvios` |
| Tamanhos | 200 itens (`/consultas/lote`), 10.000 (`/lote/clientes`), 500 CPFs (`/links`, `/conferencias`), 64 KB de corpo | schemas |
| Espera | Cabeçalho `Retry-After` no 429 | `info.description` |

Cota de consultas e custo por consulta: não documentado.

## Dados pessoais e arquivos

| Etapa | Vai | Volta |
| --- | --- | --- |
| Consulta | `cpf`, `telefone` (celular com DDD), `nome` (opcional), `lgpd_ok` | `cpf`, `nome`, ofertas, comissão |
| Gravação | Nada além do id da consulta | `link_cliente`, `link_iflow`, `login` |
| Reenvio | `cpf`, `telefone` (opcional) | propostas com `proposta` (uuid), `codigo`, `erro_icred` |
| Links | `cpfs[]` | `link`, `lead`, `telefone`, `whatsapp` |

- Não se pede benefício, nascimento, nome da mãe, endereço, conta nem
  documento.
- O único arquivo é a planilha de `POST /planilhas` (`multipart/form-data`,
  `.xlsx` ou `.csv`). Não há base64 nem URL de mídia.
- O CPF vai no **caminho** em `GET /clientes/{cpf}` e na **query** em
  `GET /consultas?cpf=`.
- As respostas trazem comissão (`comissao_rs`, `Produto.pct`,
  `Produto.comissao`), que não é dado para o cliente.

## Comparação com a Granatech

| Tema | Granatech (hoje) | iCred (especificação) | Situação |
| --- | --- | --- | --- |
| Produto | Crédito do Trabalhador (`docs/clt.md:3`) | INSS: port, port + refin, refin, novo | **Diferente** |
| Autenticação | Login e token renovado (`docs/granatech.md:35-38`) | `X-API-Key` fixa | Mais simples |
| Consentimento | SIM gravado, depois termo assinado pela API (`docs/clt.md:60-64`) | `lgpd_ok: true` | **Falta** termo e prova do lado do parceiro |
| Consulta | Abre, espera webhook, lê detalhe com margens (`docs/granatech.md:48-63`) | `POST /consultas` assíncrono, resultado por webhook | Equivalente |
| Simulação | Rota própria, com parcela e prazo escolhidos (`cliente.py:527`, `588`) | Embutida na consulta; o motor escolhe | **Falta** simular com parâmetros |
| Escolha do produto | Código do Saturday (`agent/clt/regras.py`) | Motor, por maior comissão | **Diferente** |
| Teto de valor | `simular_no_teto` reduz a parcela (`docs/granatech.md:67-73`) | Sem parâmetro de valor | **Falta** |
| Seguro | Bloco na simulação (`docs/granatech.md:72-73`) | `Produto` não tem campo de seguro | Não documentado |
| Proposta | `criar_proposta` com intenção e reconciliação pela listagem (`docs/granatech.md:77-84`) | `POST /consultas/{id}/gravar` | Equivalente, com outra forma de conferir |
| Dados do tomador e conta | `dados-tomador`, `dados-bancarios` (`cliente.py:792`, `815`) | Não existem | **Falta** (provavelmente no link do iCred; não documentado) |
| Formalização | Link de biometria do banco, encurtado (`docs/clt.md:139-142`) | iCred manda o link; `link_cliente` na resposta | Equivalente |
| Reenviar link | Turno de sistema (`docs/granatech.md:176`) | `POST /reenvios`, um a cada 6 h | Equivalente |
| Status da proposta | 10 status com ordem e finais (`bancos/granatech/status.py:52-63`) | Sem enum; só contagens e `beneficio_bloqueado` | **Falta** |
| Cancelar | `POST /propostas/{id}/cancelar` (`cliente.py:805`) | "nunca cancela proposta" | **Falta** |
| Webhook | Token em tempo constante (`docs/granatech.md:93-96`) | HMAC com timestamp, id do evento, reentrega | Melhor |
| Recuperar evento perdido | Não há; alerta de consulta parada (`docs/granatech.md:127-130`) | `GET /eventos?desde=` | Melhor |
| Cota | Diária, mensal e reaproveitamento por CPF (`docs/granatech.md:48-59`) | Só limite de gravações por dia e por minuto | Diferente |
| Ambiente de teste | api-dev e simulador (`docs/granatech.md:132-144`) | Não documentado | **Falta** |

### O que serve de molde

- `bancos/granatech/cliente.py`: HTTP com registro só de rota-modelo
  (`docs/granatech.md:42-44`), `ErroIncerto` (`cliente.py:81`) e `criar_proposta`
  com intenção antes do POST (`cliente.py:623`).
- `bancos/granatech/status.py`: ordem, finais e "status final nunca muda".
- `web/api/granatech.py` e `jobs/granatech.py`: gravar em `eventos_recebidos`,
  responder e aplicar no worker. A validação HMAC tem molde em
  `web/api/whatsapp.py:45-47`.
- `dados/cota.py`: já é por `parceiro` (`dados/modelos.py:216-222`,
  `cliente.py:322`).
- `agent/clt/turno.py` e os turnos de sistema (`docs/clt.md:81-94`): o padrão
  "evento do banco → `AgentService.continuar`" serve para `consulta.concluida`.
- `simuladores/granatech/app.py`: rotas do parceiro mais `/admin/evento` e
  `/admin/falha`.
- Como o produto é INSS, o grafo a estender é o ramo INSS (`agent/nodes.py:309`
  `read_statement`, `:448` `calculate_portability`, `:497` `present_offer`, e
  `portabilidade/`), não o `agent/clt/`.

### O que está preso à Granatech

Não há interface de banco: a decisão 0004 adia o `Protocol` até "quando o
segundo banco entrar" (`docs/decisoes/0004-sem-interface-banco-com-um-banco-so.md:16-18`).

| Onde | Acoplamento |
| --- | --- |
| `agent/context.py:31`, `:34` | Campos `granatech` e `granatech_teste` tipados como `ClienteGranatech` |
| `web/composicao.py:53-61`, `:142-169` | Montagem do cliente; a BrasilAPI só existe com a Granatech (`:61`) |
| `agent/nodes.py:136` | Entrar no ramo CLT depende de `contexto.granatech is not None` |
| `agent/clt/turno.py:18`, `:123-128` | `Turno.granatech` devolve o cliente concreto |
| `agent/clt/nos.py:32-33`, `:48`, `:53`, `:246`, `:420`, `:436` | Tipos da normalização, etapa de triagem `granatech`, consulta, simulação e teto |
| `agent/clt/regras.py:16`, `agent/clt/leitura.py:17` | Regras e leitura importam tipos e números da Granatech |
| `agent/clt/proposta.py:25-26`, `:286`, `:310` | Proposta e dados do tomador |
| `jobs/eventos.py:33`, `:56-57`, `:76` | O worker só conhece a origem `granatech` |
| `jobs/alertas.py:19`, `:82-92` | Consulta parada lê `ConsultaGranatech` |
| `dados/modelos.py:313`, `:351`, `:484` | Tabelas `consultas_granatech`, `propostas_granatech`, `homologacoes_granatech` |
| `settings.py:90-109`, `:294-295` | 14 variáveis `granatech_*`, incluindo o teto (`:104`) |
| `web/api/granatech_admin.py:56`, `web/api/links.py:17`, `:43-48` | Aba do painel e link curto |
| `web/api/evolution.py:27` | O webhook da Evolution importa `evento_id` e `token_recebido` do módulo da Granatech |
| `painel/acoes.py:195-201` | Travas de edição pelo que existe na Granatech |
| `schemas.py:77` | Motivo de handoff `granatech_indisponivel` |
| `conhecimento/clt/mensagens.yaml:29`, `:219` | Textos que citam a Granatech |
| `apps/painel/src/paginas/Granatech.tsx`, `Bancos.tsx` | Telas |

## Conflitos com o AGENTS.md

| Regra (`AGENTS.md`) | Conflito |
| --- | --- |
| 1. Auto-suficiência (`:12`) | A lista de parceiros permitidos não tem o iCred. O host é `dynatech.systems`, o mesmo do deploy do Saturday (`docs/granatech.md:251`), e a especificação cita "Maria/JEV" e a aplicação "maria". **Inferência:** pode ser um sistema interno; se for da MEX, a regra proíbe. `GET /clientes/{cpf}` mostra consultas "de todas as aplicações" |
| 2. Decisões em código (`:13`) | A escolha do produto passa a ser do motor (maior comissão), não de código do Saturday |
| 3. Consentimento (`:14`) | `lgpd_ok` é declarado por quem chama: o SIM e a prova continuam sendo do Saturday. `acao: gravar` direto e `aceitar_mudanca: true` gravam algo que o cliente não viu |
| 4. Proposta sem retry (`:15`) | `/gravar` não documenta `Idempotency-Key`. Dá para conferir por `GET /consultas/{cid}`; falta saber o comportamento com gravação em curso |
| 5. Cota (`:16`) | A regra fala só da Granatech. O iCred tem limite diário de gravações e nenhum de consultas documentado |
| 6. Teto de R$ 6.999 (`:17`) | A API não aceita valor máximo: só dá para não apresentar e não gravar a oferta acima do teto. Falta decidir se o teto vale para INSS |
| 7. Seguro (`:18`) | `Produto` não diz se há seguro nem o valor |
| 9. Dados pessoais (`:20`) | CPF no caminho e na query: o log tem de gravar a rota-modelo. Os eventos trazem CPF, nome e telefone |
| 10. Webhooks (`:21`) | Sem conflito: HMAC, id de evento e reentrega. Exige validação em tempo constante e a janela de 5 min |
| 11. Sem chamadas reais em teste (`:22`) | Não há sandbox documentado; `acao: consultar` já consulta o iCred de verdade. Seria preciso um simulador novo |
| 12. Não inventar contrato (`:23`) | Respostas de `operação` sem schema, `situacao` sem enum, `dados` livre em três eventos |
| Fora do escopo (`:25-26`) | "demais bancos" exclui o iCred. Entrar exige mudar o `AGENTS.md` e registrar a decisão. O documento de especificação da raiz não trata do iCred |

A regra 8 (segredos por variável de ambiente) não conflita: seriam duas
variáveis novas, a chave e o segredo do webhook.

## O que o código-fonte do motor respondeu

Lido em 2026-11-16 no zip `icred_api-main` (FastAPI, SQLite, Playwright). Só
leitura: nada foi executado. Os caminhos são do repositório do motor, que não
está neste repositório. Parte dos arquivos foi lida por trechos.

### O que muda a integração

- **É sistema da MEX.** `User-Agent: MEX-iCred-Worker/1.0`
  (`motor/icred_worker.py:204`); o motor roda ao lado do worker do CRM e disputa
  os mesmos logins de operador (`supervisor.py:109-111`). O modo da API não
  chama o CRM.
- **Não há API do iCred.** Playwright sobre um Chrome logado como operador no
  portal `corban.icred.digital`, mais `fetch` à API interna do portal de dentro
  da aba (`motor/gravar_simples.py:44`, `:581-587`).
- **`/gravar` grava uma proposta por contrato (card)**, na tabela de maior
  comissão de cada um; para no primeiro erro, com `GRAVADO_PARCIAL`
  (`motor/gravar_simples.py:937-940`, `:960-961`, `:975`;
  `motor/comissao_icred.py:347-353`). Só dá para restringir por tipo
  (`produtos`).
- **No Port + Refin o valor gravado pode diferir do mostrado:** o motor manda
  `settleRange.max` e aceita as tabelas alternativas
  (`motor/gravar_simples.py:872-881`); no teste, oferta de 2.501,92 e aceite com
  1.751,34 (`tests/test_worker.py:75-76`).
- **A consulta cria lead no iCred** e o `link_cliente` já vem em `COM_OFERTA`: o
  cliente pode criar a proposta pelo link sem `/gravar`
  (`motor/gravar_simples.py:1116-1117`).
- **Só aparece oferta com comissão maior que zero** (`SEM_COMISSAO`,
  `motor/gravar_simples.py:1137-1139`); taxa fora de 0,5% a 3,0% ao mês é
  descartada (`motor/ofertas_icred.py:202-206`).
- **A gravação vai com cadastro fictício fixo** (nascimento `2000-01-01`, e-mail
  genérico, sem endereço) e `disbursementPix: None`
  (`motor/gravar_simples.py:48-53`, `:882-883`).

### Situações (`GET /situacoes`, `esquemas.py:16-33`)

| Situação | Significado | Aceita novo `/gravar` |
| --- | --- | --- |
| `COM_OFERTA` | Oferta com comissão; pode gravar até `valido_ate` | Sim |
| `GRAVADO` | O iCred aceitou o pedido; o link sai pelo iCred | Não |
| `GRAVADO_PARCIAL` | Parte dos contratos gravada | Não |
| `JA_GRAVADO` | O motor já gravou para o CPF | Não |
| `PROPOSTA_EXISTENTE` | Já há proposta em andamento no CPF (também na consulta) | Não |
| `TELEFONE_VINCULADO` | Telefone ligado a outro CPF; exige outra consulta | Não |
| `RECALCULO` | As ofertas mudaram ou a consulta venceu | Só na etapa `gravar` |
| `SEM_PRODUTO_PERMITIDO` | Só havia tipos desligados | Só na etapa `gravar` |
| `SEM_COMISSAO`, `INELEGIVEL`, `SEM_BENEFICIO` | Sem oferta | Só na etapa `gravar` |
| `DADOS_PENDENTES`, `CONTA_PIX_PENDENTE` | O iCred recusou a gravação | Só na etapa `gravar` |
| `DESAFIO_CLOUDFLARE`, `ICRED_INSTAVEL`, `ERRO` | Falha técnica | Só na etapa `gravar` |

Final é o `estado` (`concluida`, `cancelada`), não a `situacao`
(`consultas.py:132-134`, `:143-144`). `etapa` e `acao`: `consultar` ou `gravar`
(`db.py:26-27`). Na etapa `consultar`, tudo que não é `COM_OFERTA` encerra
aquela consulta.

### Respostas às perguntas

1. **Quem mantém.** MEX, desenvolvido pela Dynatech (`DEPLOY_VPS.md:15`,
   inferência pelo caminho). Roda em VPS com Dokploy ou compose
   (`DEPLOY_VPS.md:1-4`).
2. **Homologação.** Não há; a URL do portal é de produção
   (`motor/gravar_simples.py:44`). `acao: consultar` simula de verdade. Sem
   tocar o iCred só há `POST /eventos/teste` e o portal falso dos testes
   (`tests/conftest.py:90-189`).
3. **Base URL.** Não está no código.
4. **Chave.** Gerada à mão e colada no JSON `ICRED_APLICACOES`; mínimo de 32
   caracteres; não expira; trocar exige reiniciar (`config.py:86-120`).
5. **Webhook.** `webhook_url` e `segredo_webhook` no mesmo JSON
   (`config.py:105-113`). Aplicação sem segredo que usa `callback_url` recebe o
   evento sem assinatura (`webhooks.py:55-56`).
6. **Situações.** Tabela acima.
7. **O que `/gravar` grava.** Uma proposta por card; não dá para escolher uma.
8. **Prazo, parcela, valor.** Não há parâmetro (`esquemas.py:36-54`,
   `:134-142`).
9. **Segundo `/gravar`.** `409 nao_gravavel` (`consultas.py:144`, `:152`). Não
   aceita `Idempotency-Key` (`rotas/consultas.py:81-82`).
10. **"Um CPF é gravado uma vez".** Global e permanente, num arquivo indexado só
    pelo CPF, marcado antes do POST (`motor/gravar_simples.py:156-171`, `:935`).
    Liberar um CPF não está no código.
11. **`valido_ate`.** 15 minutos, configurável de 1 a 240 (`config.py:128`).
12. **Status da proposta.** Existem (`waiting-sign`, `finished`, `canceled`,
    `reproved`, entre outros, `relatorios.py:68-73`), mas não chegam por
    webhook: só em `GET /gravados`, escopo `operacao`. `consulta.link_atualizado`
    só dispara quando muda a contagem de propostas, de link enviado ou o
    bloqueio (`worker.py:362-364`).
13. **Conferência.** Só com `POST /conferencias`; não há agendador
    (`supervisor.py:86-118`). Logo depois de `GRAVADO`, `propostas` e
    `link_enviado` vêm nulos (`worker.py:160`).
14. **Link do cliente.** Não está no código. Inferência: conta, PIX e dados
    reais são completados ali.
15. **Seguro e CET.** Não estão no código; o motor lê taxa, bruto, líquido,
    parcela e prazo (`motor/ofertas_icred.py:165-171`).
16. **`lgpd_ok`.** Só o booleano; nem é gravado (`db.py:18-52`).
17. **Limites.** Por aplicação, 60 por minuto e 500 gravações por dia por padrão
    (`config.py:62-63`); conta pedidos, não gravações efetivas. Por login, 2.000
    simulações por dia, divididas entre todas as aplicações e o lote
    (`motor/config_icred.py:42`).
18. **`beneficio_bloqueado`.** O cliente precisa desbloquear o benefício no Meu
    INSS (`worker.py:338`). O campo não sai no evento (`consultas.py:91-103`).
    `link_iflow` é a tela do operador, não é para o cliente.
19. **`TELEFONE_VINCULADO`.** O robô nunca transfere o telefone; é preciso
    consultar de novo com outro número (`motor/gravar_simples.py:1097-1098`).
20. **Escopos.** `consultas` e `consultas:gravar` bastam. `POST /reenvios` e
    `POST /links` acham o cliente pelo CPF sem filtrar por aplicação
    (`rotas/reenvios.py:24-31`, `rotas/links.py:61`).
21. **Rotas de operação.** Sem modelos; as formas estão em `relatorios.py`.
22. **Reenvio.** Vale `POST /reenvios`: o Chrome bloqueia o reenvio por padrão e
    libera uma chamada por proposta (`motor/gravar_simples.py:347-354`).
23. **Cancelar.** Não há: toda chamada com "cancel" é abortada no Chrome.
24. **Nome.** O motor devolve o nome enviado, não o do cadastro
    (`consultas.py:63`, `:94`).
25. **`portabilidade_pausada`.** Muda sem aviso e sem evento; só `GET /saude`
    mostra (`motor/ofertas_icred.py:22-27`).

### Para o simulador

- Envelope do evento: `eventos.py:48-49`. O `dados` é o dicionário de
  `consultas.py:91-103`; um card real de Port + Refin está em
  `tests/conftest.py:78-87`.
- Depois de `/gravar`: `etapa: gravar`, `situacao: GRAVADO`, `valido_ate: null`
  (inferência de `worker.py:199-207`).
- Tempo real de uma consulta: de 20 s a mais de 2 min, um cliente por login por
  vez (`motor/gravar_simples.py:845`, `:1121`).
- Limite diário do login esgotado: a consulta fica `na_fila` sem evento nem erro
  até virar o dia (`worker.py:425-426`).
- Worker que cai no meio da gravação: a nova tentativa responde `JA_GRAVADO`
  mesmo que a proposta tenha sido criada (`worker.py:491-493`).
- Webhook: 6 tentativas no total, sem seguir redirecionamento
  (`webhooks.py:28-33`).
- O id do evento é segundo mais 8 hex aleatórios: `desde=` pode pular um evento
  do mesmo segundo (`eventos.py:29-30`, `:55-60`).

### Continua sem resposta

- Base URL de produção e quais aplicações estão cadastradas.
- O que o cliente faz no link do iCred; seguro e CET.
- Custo por consulta e limites do próprio iCred.
- Como liberar um CPF marcado como `JA_GRAVADO`.
