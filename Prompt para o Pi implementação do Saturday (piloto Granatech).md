# Prompt para o Pi: implementação do Saturday (piloto Granatech)

Nov 10, 2026 · @Carlos Eduardo Ferreira Fernandes

## Como usar

Salve as seções de "Papel" até "Testes" como `AGENTS.md` na raiz do repositório `saturday`. O Pi lê esse arquivo antes de cada pedido, então o contexto e as regras valem em toda sessão.

- Conduza **uma fase por sessão**, com o pedido "Implemente a Fase N do AGENTS.md".
- Abra cada fase com `/gather-context-and-clarify`: o Pi lê o AGENTS.md e o código e pergunta o que estiver ambíguo.
- O plano da fase passa pelo Plannotator; só implemente depois de aprovado.
- Feche cada fase com `/review-loop` e confira os critérios de aceite antes de seguir.
- Nunca coloque credenciais reais no `AGENTS.md`, no chat do Pi ou no repositório: só no `.env` local e no Dokploy.

## Ferramentas do Pi nesta implementação

A configuração atual do Pi já cobre plano, subagentes e auditoria; use cada ferramenta na etapa indicada.

| Etapa | Ferramentas |
| --- | --- |
| Planejar a fase | `/gather-context-and-clarify`, Plannotator, `rpiv-ask-user-question` para dúvidas, `rpiv-todo` com os critérios de aceite |
| Pesquisar documentação (Meta, BrasilAPI, LangGraph) | `pi-web-access`, `/parallel-research` |
| LangGraph | `langgraph-fundamentals`, `langgraph-persistence` (PostgresSaver, Fase 1), `langgraph-human-in-the-loop` (handoff), `langchain-dependencies` (versões) |
| Refatorar e navegar (Fase 0) | `pi-lens-lsp-navigation`, `pi-lens-ast-grep` |
| Subagentes | `pi-subagents` em paralelo só para leitura e pesquisa; uma única sessão escreve código por vez |
| Segurança | `security-threat-model` na Fase 1 (modelo de ameaças em `docs/`); `insecure-defaults` e `semgrep` em toda fase; `agentic-actions-auditor` no CI (Fase 0); `supply-chain-risk-auditor` nas dependências do core e do painel |
| Revisão | `/review-loop`, `code-reviewer`, `differential-review` sobre o diff da fase, `spec-to-code-compliance` contra este AGENTS.md |
| Sessões longas | `context-mode` e `ctx-stats` |

- **`pi-mcp-adapter`:** não conecte, nestas sessões, servidores MCP de sistemas da MEX (Supabase, CRM, Lovable) nem do GitHub com escrita. Um erro do agente ali atinge produção.
- **`swarm` e `council-mode`:** não são necessários; as decisões de arquitetura já estão tomadas neste documento.

## Papel, objetivo e escopo

Você é o engenheiro responsável por evoluir o **Saturday** de um agente de portabilidade INSS → C6 para o agente de atendimento autônomo da MEX, começando pelo Crédito do Trabalhador (CLT) pela Granatech.

**Ponto de partida:** o repositório atual é Python 3 com `uv`, FastAPI, LangGraph (checkpointer SQLite), OpenRouter, logs em JSON, testes com `pytest`, Dockerfile e docker-compose. O grafo vive em `src/saturday/agent/`, as regras e o cálculo do INSS em `src/saturday/portabilidade/`, as integrações em `src/saturday/services/` e as rotas em `src/saturday/web/`. Preserve o comportamento do ramo INSS e todos os testes existentes.

**Objetivo do piloto:** um cliente CLT escreve num número novo de WhatsApp, passa por uma triagem que não gasta cota, autoriza a consulta, recebe uma simulação da Granatech, aceita, e o agente cria a proposta, acompanha a biometria e avisa o pagamento, tudo sem intervenção humana. A equipe acompanha e assume conversas por um painel web próprio.

**Dentro do escopo:**

- Monorepo que sobe inteiro com `docker compose`, publicado no Dokploy.
- Migração do estado para Postgres, envio por outbox e storage S3.
- Canal WhatsApp Cloud API (Meta) com notificações proativas e modelos.
- Painel da equipe (React + Vite + TypeScript) com login e senha.
- Ramo CLT com triagem, consentimento e o adaptador Granatech completo (consulta, simulação, proposta, pós-venda).
- Simulador da Granatech e da Meta para desenvolvimento e testes.

**Fora do escopo agora:** Finqia, V8, Presença, C6 CLT, Facta e demais bancos; FGTS; NovaVida; qualquer dependência do CRM da MEX. Deixe apenas as interfaces prontas para recebê-los (adaptador de banco, fonte cadastral).

## Regras inegociáveis

Se uma tarefa parecer exigir quebrar uma destas regras, pare e pergunte.

1. **Auto-suficiência:** o Saturday não chama, não lê e não escreve em nenhum sistema da MEX (CRM, Supabase do Deu Plim, hub `mex-granatech-api`). Só parceiros externos: Meta, Granatech, BrasilAPI, OpenRouter.
2. **Decisões em código:** triagem, consentimento, regras de banco, cálculos, escolha de produto e transições de estado são determinísticos e testados. O LLM só classifica intenção e responde dúvidas ancoradas na FAQ; nunca escreve números, valores ou condições.
3. **Consentimento do cliente:** nenhuma consulta e nenhuma proposta sem um "SIM" explícito do próprio cliente, conferido em código, com prova gravada. Nunca simule aceite com dados de aparelho inventados.
4. **Proposta nunca repetida automaticamente:** `POST` de proposta não tem retry. Grave a intenção antes; em resultado incerto (timeout, 5xx), procure a proposta na listagem antes de qualquer nova tentativa.
5. **Cota da Granatech:** nunca abra consulta sem passar pela triagem, pelo consentimento e pelo controle de cota (teto mensal, limite diário, reaproveitamento por CPF).
6. **Teto de R$ 6.999:** nenhuma simulação é apresentada e nenhuma proposta é criada com valor liberado acima disso.
7. **Seguro:** toda oferta com seguro diz que ele está incluído, o valor e que é opcional.
8. **Segredos:** só por variável de ambiente. O serviço não sobe se faltar um obrigatório. Nada de chave, token ou senha em código, teste, fixture, log ou commit.
9. **Dados pessoais:** CPF, e-mail, telefone, nome da mãe e endereço mascarados em logs. O log de chamadas externas guarda só metadados (rota, status, tempo, IDs). Mídia e documentos só em storage privado, nunca em base64 no estado do grafo.
10. **Webhooks:** gravar, responder 200 rápido e processar no worker. Assinatura validada quando o parceiro assina (Meta, em tempo constante); token longo quando não assina. Processamento idempotente e sem regressão de estado após status final.
11. **Sem chamadas reais em teste:** testes e desenvolvimento usam os simuladores. Nunca chame a Granatech de produção nem envie WhatsApp real fora do ambiente de produção.
12. **Não invente contratos de API:** use só os campos e rotas descritos aqui. O que estiver marcado como pendente fica atrás de flag e com `TODO(granatech)`.

## Arquitetura alvo e estrutura do monorepo

Um pacote Python único com duas entradas (API e worker), um front-end separado e os dados em Postgres e S3.

```text
saturday/
├── apps/
│   ├── core/                    # pacote Python (uv)
│   │   ├── src/saturday/
│   │   │   ├── agent/           # grafo: roteador, ramo inss/, ramo clt/
│   │   │   ├── portabilidade/   # INSS → C6 (existente, preservar)
│   │   │   ├── canais/          # whatsapp/, chat/ (contrato HTTP atual)
│   │   │   ├── bancos/          # base.py (interface), granatech/
│   │   │   ├── fontes/          # base.py (fonte cadastral), brasilapi.py
│   │   │   ├── consentimento/   # regra do SIM, provas
│   │   │   ├── notificacoes/    # fila, janela de 24 h, modelos
│   │   │   ├── dados/           # SQLAlchemy, repositórios, outbox, travas
│   │   │   ├── storage/         # cliente S3
│   │   │   ├── web/             # FastAPI: pública, webhooks, admin
│   │   │   ├── jobs/            # tarefas do worker
│   │   │   ├── settings.py
│   │   │   ├── api.py           # entrada: uvicorn
│   │   │   └── worker.py        # entrada: loop do worker
│   │   └── tests/
│   └── painel/                  # React + Vite + TypeScript
├── regras/granatech.yaml        # regras do banco, com vigência
├── conhecimento/                # FAQ e mensagens fixas por produto
├── migrations/                  # Alembic
├── simuladores/                 # granatech/, meta/ (FastAPI pequeno)
├── infra/                       # scripts, configuração de backup
├── docs/
├── compose.yaml
├── compose.override.yaml
├── .env.example
└── AGENTS.md
```

**Fluxo:** a Meta e a Granatech chamam os webhooks da `api`, que grava o evento e responde 200. O `worker` consome a fila, roda o turno do grafo sob a trava da conversa e grava a resposta no outbox na mesma transação. O `worker` entrega o outbox pela Meta, respeitando a janela de 24 h. O `painel` fala só com a API admin.

**Interfaces para o futuro:**

- `bancos/base.py`: `Banco` com `elegivel(ficha)`, `consultar`, `simular`, `criar_proposta`, `status`, `processar_evento`. A Granatech é a primeira implementação.
- `fontes/base.py`: `FonteCadastral` com `buscar_por_cpf` e `buscar_empresa_por_cnpj`. A BrasilAPI implementa só empresa; a NovaVida entra depois.
- `canais/base.py`: `Canal` com `enviar_texto`, `enviar_modelo`, `janela_aberta`.

## Fases de implementação

Oito fases, uma por sessão, cada uma terminando com testes verdes e um commit. Não avance com critério de aceite pendente.

**Fase 0. Monorepo, compose e CI** (sem mudar comportamento)

- Mover o código para `apps/core/`, criar a árvore da arquitetura alvo, `compose.yaml`, `compose.override.yaml` e `.env.example`.
- GitHub Actions: lint, tipos e `pytest` em cada push.
- Aceite: `docker compose up` sobe a API atual; todos os testes existentes passam sem alteração de asserções.

**Fase 1. Dados e confiabilidade**

- Postgres com SQLAlchemy e Alembic; checkpointer do LangGraph em Postgres (`PostgresSaver`).
- Trava por conversa com `pg_advisory_xact_lock` no lugar do `threading.Lock`.
- Tabelas: `conversas`, `mensagens`, `outbox`, `eventos_recebidos`, `consentimentos`, `chamadas_externas` (só metadados), `cota`, `usuarios_painel`, `auditoria`.
- Outbox gravado na mesma transação do turno; worker entrega com retry e backoff.
- Storage S3 (MinIO interno ou externo) para anexos; o estado do grafo guarda só a referência.
- Correções do ramo INSS: `message_id` repetido devolve a resposta já dada (não vazia); limite de 20 MB no corpo da requisição; retenção apaga também checkpoints antigos e anexos; o desconto da margem extrapolada vai para um contrato elegível.
- Aceite: dois workers processando a mesma conversa em paralelo não duplicam turno; um envio que falha é reentregue; teste de retenção comprova que o extrato some de todos os checkpoints.

**Fase 2. Canal WhatsApp**

- Webhook da Meta (verificação, assinatura, deduplicação), mídia, transcrição de áudio, status de entrega, envio com divisão em partes, controle da janela de 24 h e envio de modelos.
- Simulador da Meta em `simuladores/meta`.
- Aceite: uma conversa ponta a ponta pelo simulador (texto, foto do extrato INSS, áudio) chega ao grafo e volta pelo outbox; mensagem com janela fechada sai como modelo.

**Fase 3. Painel mínimo e API admin**

- Login e senha (argon2id), bloqueio após 5 tentativas, sessão com expiração, perfis atendente e gestor, auditoria de cada ação.
- Inbox, conversa (enviar, assumir, devolver para a IA, transferir), ficha com dados mascarados, alertas e contador de cota.
- Atualização em tempo real por SSE.
- Aceite: atendente assume uma conversa, responde, e a IA fica em silêncio até ela devolver; revelar um CPF gera registro na auditoria.

**Fase 4. Cliente Granatech e simulador**

- Cliente HTTP com token em cache, retry só em GET, normalização de consulta e simulação, teto de R$ 6.999, controle de cota, receptor de webhook e reconciliação.
- Simulador da Granatech com as respostas reais da dev (ver especificação).
- Aceite: testes cobrem cada status de consulta e proposta, eventos duplicados e fora de ordem, token expirado e o ajuste ao teto.

**Fase 5. Ramo CLT até a oferta**

- Roteamento para CLT, triagem, BrasilAPI, idade × prazo, consentimento, consulta, conferência, escolha de vínculo, simulação e mensagem de oferta.
- Aceite: jornadas completas pelo simulador para os casos aprovado, reprovado em cada pergunta da triagem, empresa reprovada, sem margem, mulher de 55 anos (prazos limitados) e cota esgotada; nenhuma consulta é aberta sem consentimento.

**Fase 6. Proposta e pós-venda**

- Aceite com resumo e SIM, coleta dos dados que faltam, criação da proposta (atrás de `GRANATECH_PROPOSTA_ATIVA`), dados do tomador, link de biometria, eventos de status e notificações por modelo.
- Aceite: proposta criada uma única vez mesmo com timeout simulado; cada status gera a mensagem certa; pagamento confirmado encerra a jornada.

**Fase 7. Deploy e operação**

- Guia de deploy no Dokploy (`docs/deploy.md`), healthchecks, limites de CPU e memória, backup do Postgres e do storage com teste de restauração.
- Script `scripts/homologacao_granatech.py` que gera as evidências das Fases 1 e 2 da Granatech contra a api-dev.
- Aceite: um ambiente de homologação sobe do zero seguindo só o guia.

## Especificação: API Granatech

API de parceiros, Bearer token; tudo abaixo foi testado na dev ou consta do Swagger. Itens marcados como **pendente** dependem de resposta da Granatech.

**Acesso**

- Base: `GRANATECH_BASE_URL` (dev: `https://api-dev.granatech.com.br`; produção: pendente).
- Login: `POST /api/v1/auth/login` com `{"chave_api": "..."}` → `201 {"token": "...", "expira_em": "1h"}`. Aceite também segundos, minutos ou data ISO em `expira_em`; na dúvida, 1 h. Renove 5 min antes; em 401, renove e repita uma vez.
- Retry: GET repete 1 vez em erro de rede ou 5xx (espera 1,5 s). POST e PATCH nunca repetem, exceto após 401.

**Rotas do consignado (`/api-consignado/v1`)**

| Método e rota | Uso | Notas |
| --- | --- | --- |
| `GET /consulta-saldo?cpf&nome&telefone` | Abre a consulta | Telefone com 11 dígitos. Devolve `id`, `status` e `link_termo_consentimento`. **Gasta cota** |
| `POST /termo-consentimento` | Assina o termo | Corpo: `cpf`, `email`, `nome`, `telefone`, `id_consulta` (todos obrigatórios). Rota antiga `consent-term` dá 400: não usar |
| `GET /consulta-saldo/{id}` | Detalhe | Sem campo de status: com margens = pronta. Traz `margens[]` e `pessoa_natural` |
| `GET /consulta-saldo/usuario?pagina&filterBy&filtrar_por&valor_filtro` | Lista por CPF | Envie `filterBy` e `filtrar_por` (pendente qual vale) |
| `GET /simulacao/{id_produto}?id_margem&numero_parcelas&idade&valor_parcela&seguro&id_empresa_seguro&id_produto_seguro` | Simula | Responde `resultado_da_simulacao_com_seguro` e/ou `_sem_seguro` |
| `POST /propostas` | Cria proposta | Formato da resposta pendente: aceite `id`, `id_proposta` ou `data.id` |
| `POST /propostas/{id}/dados-tomador` | Dados do cliente | Ver campos abaixo |
| `GET /propostas/{id}` | Status |  |
| `GET /propostas/lista?pagina&tamanho_pagina&status&termo_busca` | Lista | Usada para reconciliar proposta incerta |
| `PATCH /propostas/{id}/dados-bancarios` | Corrige conta | Corpo pendente: atrás de flag |
| `POST /propostas/{id}/cancelar` | Cancela |  |
| `GET /bancos` | Bancos para o Pix | Filtrar `habilitado` |

**Normalização da consulta:** de `margens[]` extraia por vínculo `id_margem` (`id`), `margem`, `nome_empregador`, `documento_empregador`, `elegivel_empregador` e `produtos[]` (`id`, `nome`, `parcelas`, `taxa_mensal`, `seguro`, `margem`, `limite_minimo`, `limite_maximo`, `id_empresa_seguro`, e `id_cobertura_seguro` → enviado como `id_produto_seguro`). De `pessoa_natural`: `name`, `document`, `birth_date`, `age`, `gender`, `mother_name`, `civil_status`, `email`, `phone_number`, `address` (`zip_code`, `address_name`, `number`, `complement`, `district`, `city`, `uf`). Números podem vir como `"1.500,00"`: normalize.

**Simulação:** o valor liberado ao cliente é `valor_solicitado` (exemplo da dev: R$ 4.619,53 liberado + R$ 175,28 de IOF + R$ 503,32 de seguro = R$ 5.298,13 financiado). Guarde também `valor_parcela`, `numero_parcelas`, `taxa_mensal`, `taxa_anual`, `cet_mensal`, `cet_anual`, `valor_iof`, `valor_seguro`, `valor_total_financiado`, `valor_total_divida`, `parcelas[0].dt_vencimento`, `id_empregador` e `info_seguradora`. Informe sempre o bloco que **voltou** (`seguro_aplicado`), não o pedido: na dev, `seguro=false` é ignorado.

**Escolha do produto:** entre os produtos do vínculo, o de maior comissão (CMR48 7%; demais com seguro 4%; sem seguro 0,5%) cujo prazo termina antes do limite de idade; se o cliente pedir sem seguro, o produto sem seguro.

**Teto de R$ 6.999:** se o liberado passar do teto, nova parcela = `floor(parcela × 6999 / liberado × folga × 100) / 100`, com folga 1 na 1ª tentativa e `1 − 0,005 × (tentativa − 1)` nas seguintes; até 4 novas simulações; abaixo de R$ 45 de parcela, sem oferta. A resposta indica que o valor foi limitado.

**Corpo da proposta** (`POST /propostas`): `id_empregador`, `id_consulta`, `id_produto`, `id_margem`, `informacoesFinanceira[]` (`tipo_empregador` pendente, padrão 1 por config; `documento_empregador`, `valor_solicitado`, `valor_total_financiado`, `valor_parcela`, `numero_parcelas`, `taxa_mensal`, `valor_seguro`, `valor_liberado_habilitado: true`, `cet_anual`, `cet_mensal`, `valor_iof`, `taxa_anual`) e `informacaoDeSeguros` (`id_empresa_seguradora`, `valor_total_financiado`, `numero_parcelas`, `id_externo` como texto, `valor_seguro`, `iof`; sem seguro: pendente).

**Dados do tomador:** `nome_completo`, `estado_civil`, `data_nascimento`, `telefone_endereco`, `nome_completo_mae`, `cep`, `endereco`, `numero_endereco`, `bairro`, `cidade`, `estado`, `complemento`, `cpf`, `tipo_dados_bancarios: "dados_bancarios"`, `banco_detalhe` (`agencia`, `digito_agencia`, `numero_conta`, `digito_conta`, `tipo_conta`: `conta_corrente` ou `conta_poupanca`, `banco_codigo`).

**Webhooks recebidos**

- Consulta: `{id_solicitacao, id_proposta, cpf, status, user_id, corban_id, tipo: "CONSULTA"}`. Status: `AWAITING_CLIENT_AUTHORIZATION`, `PROCESSING`, `SUCCESS`, `PENDING`, `NO_MARGIN`, `USED`, `UNEXPECTED_ERROR`; também já vistos `FIDUCIARY_INSTITUTION_NO_AUTHORIZATION` e `WORKER_MUST_CANCEL_RETURN_REQUEST` (significado pendente: handoff).
- Proposta: `{tipo: "proposta", status_da_proposta, tipo_notificacao, id_proposta, informacoes}`. Use status **e** `tipo_notificacao`. `PAGO` e `PROPOSTA_PAGA` são a mesma coisa. Finais: `PAYED`, `CANCELED`, `REPROVED`, `CANCELED_BY_CLIENT`.
- Segurança: a Granatech não documenta assinatura. Aceite o token em `?t=`, `Authorization: Bearer` ou `x-webhook-token`, comparado em tempo constante, e não registre a query string.

| Status / notificação | Ação do agente |
| --- | --- |
| `PENDING_CONFIRMATION` / `AGUARDANDO_CONFIRMACAO` | Informa que a proposta foi criada |
| `PENDING_USER_REVIEW` / `AGUARDANDO_REVISAO_USUARIO` | Handoff com `informacoes` |
| `PENDING_FORMALIZATION` / `AGUARDANDO_FORMALIZACAO` | Envia o link de biometria (`url_seguranca_identidade` do `GET /propostas/{id}`) |
| `BLOQUEIO_DE_SALDO_EM_ANDAMENTO`, `BLOQUEIO_SALDO`, `FORMALIZACAO_EM_ANDAMENTO` | Só atualiza (agrupar avisos) |
| `PENDING_BANK_ANALYSIS` / `AGUARDANDO_ANALISE_BANCO` | "O banco está analisando" |
| `PENDING_PAYMENT` / `SUCESSO_SEGURANCA_IDENTIDADE` | Identidade aprovada, pagamento a caminho |
| `PENDING_REFORMALIZATION` / `REFAZER_SEGURANCA_IDENTIDADE` | Reenvia o link com dicas de foto |
| `PENDING_USER_REVIEW` / `FALHA_PAGAMENTO` | Pede nova conta; na 2ª falha, handoff |
| `REPROVED` / `REPROVADO` | Informa e encerra |
| `CANCELED` (qualquer) | Traduz `informacoes` e encerra |
| `PAYED` / `PAGO` / `PROPOSTA_PAGA` | Confirma o pagamento e encerra |
| Desconhecido | Grava, responde 200 e faz handoff |

## Especificação: jornada CLT, triagem e mensagens

O ramo CLT é uma máquina de estados no LangGraph; cada etapa tem nó próprio, mensagem fixa e testes.

**Etapas** (`clt.etapa` no estado): `abertura` → `identificacao` → `triagem` → `empresa` → `consentimento` → `consultando` → `escolha_vinculo` → `oferta` → `aceite` → `dados_proposta` → `proposta` → `formalizacao` → `pago`, com saídas `nao_elegivel`, `recontato` e `handoff`. Enquanto aguarda um evento (`consultando`, `formalizacao`), o cliente pode fazer perguntas, respondidas pela FAQ sem mudar a etapa.

**Abertura:** a primeira mensagem do ramo inclui: "Vou usar os dados do seu emprego para encontrar, entre os bancos parceiros da MEX, a melhor condição para você."

**Identificação:** CPF (11 dígitos, dígito verificador, não repetido), nome completo (2 palavras ou mais), data de nascimento e sexo. Dois erros seguidos no mesmo dado → handoff.

**Triagem (sem gastar cota)**

| Pergunta | Segue se |
| --- | --- |
| Trabalha de carteira assinada? | sim |
| Há quanto tempo está na empresa atual? | 12 meses ou mais (menos: recontato na data em que completa 12) |
| É estagiário, está em experiência, tem contrato com data para terminar, está em aviso prévio ou em licença-maternidade? | não |
| Já tem empréstimo com a Granatech? | não |
| A empresa tem 30 funcionários ou mais? | sim |
| CNPJ ou nome da empresa | passa na checagem da BrasilAPI |

**Empresa:** `GET https://brasilapi.com.br/api/cnpj/v1/{cnpj}` com cache de 30 dias por CNPJ. Reprova se a situação cadastral não for ATIVA, `data_inicio_atividade` tiver menos de 24 meses, `opcao_pelo_mei` for verdadeiro, `codigo_porte` for 1 (microempresa) ou a razão social indicar recuperação judicial ou extrajudicial, falência, massa falida ou liquidação. Se o cliente só souber o nome, peça o CNPJ (está no holerite).

**Idade × prazo:** 21 anos ou mais. Um prazo P é permitido se `data_nascimento + limite` for posterior a `hoje + P meses`, com limite de 57 anos para mulher e 62 para homem. Sem nenhum prazo permitido (17, 25, 36 ou 48), não segue. Depois da consulta, confira de novo com `gender` e `birth_date` do `pessoa_natural`; se divergir do informado, vale o da Granatech.

**Cota:** teto mensal `GRANATECH_COTA_MENSAL` (padrão 500), limite diário `GRANATECH_COTA_DIARIA` e reaproveitamento de consulta do mesmo CPF dos últimos `GRANATECH_REAPROVEITAR_DIAS` dias (lista por CPF antes de abrir). Alerta no painel a 80% do mês. Cota esgotada → mensagem de "volto a falar com você" e recontato no dia seguinte.

**Consentimento:** peça e-mail (obrigatório para o termo) e confirme o celular. Texto fixo:

> Para eu ver quanto você tem disponível, preciso da sua autorização para o banco consultar os dados do seu emprego (empresa, salário e margem) no sistema do governo. É só a consulta, não contrata nada. Você autoriza? Responda SIM.

A resposta vale como SIM quando a última mensagem do cliente casa com `(^|[^\p{L}])(sim|autorizo|aceito)([^\p{L}]|$)` (sem distinção de maiúsculas), não contém negação (`não`, `nao`, `nunca`, `jamais`) e responde à pergunta de autorização. Testes obrigatórios recusam "ok", "pode ver", "simulação", "sim? não sei" e "não, sim depois". A prova (`consentimentos`) guarda tipo, texto mostrado e versão, resposta literal, `wamid`, horário e CPF. Termo pela API; se falhar, envie o `link_termo_consentimento` como plano B.

**Oferta:** depois da simulação, mensagem fixa:

> Boa notícia, {nome}! Consegui uma condição para você: R$ {liberado} liberados na sua conta, em {n} parcelas de R$ {parcela} descontadas no salário. Taxa de {taxa}% a.m. (CET de {cet}% a.m.). Já inclui o seguro Super Proteção (R$ {seguro}), que cobre desemprego, morte e invalidez. Ele é opcional: se preferir sem seguro, é só me dizer que eu refaço a simulação. Quer seguir com essa proposta?

O cliente pode pedir outro prazo ou parcela menor; o agente simula de novo dentro das regras.

**Aceite:** resumo fechado com os mesmos valores e um SIM explícito, gravado como consentimento do tipo `proposta`.

**Dados da proposta:** confirme nome da mãe e endereço vindos da Granatech; peça só estado civil e conta (banco, agência, conta e dígito) num banco da lista `GET /bancos`. A conta deve ser do próprio cliente.

**Mensagens fixas:** todas em `conhecimento/clt/mensagens.yaml`, com chave, texto e variáveis; nada de texto de cliente espalhado no código. Um teste garante que toda chave usada existe e toda variável é preenchida.

## Especificação: WhatsApp e painel

O canal segue a WhatsApp Cloud API (Graph `v23.0`, configurável) e porta o que já funciona em produção na MEX, com as correções indicadas.

**Receber (`/webhooks/whatsapp`)**

- `GET`: responde `hub.challenge` se `hub.mode=subscribe` e `hub.verify_token` confere.
- `POST`: valida `X-Hub-Signature-256` (HMAC-SHA256 do corpo cru com `WHATSAPP_APP_SECRET`, comparação em tempo constante); assinatura inválida → 401. Grava e responde 200; o worker processa.
- Atende só os números configurados (`metadata.display_phone_number`).
- Deduplica por `wamid` (índice único). Marca a mensagem como lida.
- Tipos: `text`, `button`, `interactive` (título da resposta), `audio` (transcrição; se falhar, pede texto), `image` e `document` (storage; foto e PDF vão como anexo ao grafo, até 4,5 MB para leitura), `video`, `location`, `contacts`, `sticker` e `reaction` (só registrados).
- Mídia em dois passos: `GET /{media_id}` com o token e depois a URL devolvida; guardar em `whatsapp/{celular}/{wamid}.{ext}`, limite de 50 MB.
- Guarde `referral` (anúncio Click to WhatsApp) e os `statuses` (sent, delivered, read, failed) na mensagem correspondente.
- Celular: tirar o 55 e completar o nono dígito em celulares de 10 dígitos.

**Enviar (worker, a partir do outbox)**

- O cliente fica preso ao `phone_number_id` em que escreveu por último; clientes novos entram em rodízio entre os números ativos.
- Janela de 24 h desde a última mensagem do cliente: aberta → texto livre, dividido por linha em branco (máximo 5 partes, 0,9 s entre elas); fechada → modelo aprovado, nunca texto (a Meta recusa com o código 131047).
- Retry com esperas de 2, 5 e 10 s só em erro temporário: HTTP 5xx, sem resposta, ou códigos 1, 2, 4, 80007, 130429, 131000, 131016, 131048, 131056, 133004.
- Modelos do piloto (`pt_BR`): `atualizacao_pedido`, `autorizacao_pendente`, `assinatura_pronta`, `assinatura_refazer`, `dados_bancarios_pendentes`, `pagamento_confirmado` (utilidade) e `recontato_tempo_casa` (marketing, só com opt-in; "Não quero receber" grava opt-out). Botões de URL apontam para `https://{DOMINIO}/l/{codigo}`, que redireciona ao link vigente do banco.
- Aviso proativo com janela fechada: envia `atualizacao_pedido`; quando o cliente responde, entrega a mensagem completa que ficou na fila.

**Painel (React + Vite + TypeScript)**

- Autenticação: e-mail e senha com argon2id, 5 tentativas e bloqueio de 15 min, sessão em cookie `HttpOnly`, `Secure`, `SameSite=Strict`, expiração de 8 h, CSRF nas ações. Primeiro gestor criado por comando (`saturday criar-usuario`).
- Perfis: atendente (conversas) e gestor (tudo, inclusive configuração e usuários).
- Telas: inbox (filas com IA, aguardando humano, com humano, alertas; busca; não lidas; indicador de janela), conversa (histórico com mídia, transcrição e status; enviar texto ou modelo; assumir, devolver, transferir), ficha (dados mascarados, botão revelar com auditoria; etapa CLT; consulta, simulação e proposta Granatech; provas de consentimento), alertas, configuração (bancos ligados, números, modelos, regras só leitura), números (funil, cota, custos).
- Enquanto a conversa está com humano, o agente não responde; eventos de banco viram alerta para quem está com a conversa.
- Toda ação de usuário grava `auditoria` (quem, o quê, quando, alvo).

## Variáveis de ambiente e compose

Todas as variáveis do Saturday mantêm o prefixo `SATURDAY_` de hoje; nesta especificação aparecem sem ele. O `.env.example` documenta todas, sem valores reais.

| Variável | Padrão | Uso |
| --- | --- | --- |
| `ENVIRONMENT` | `dev` | `dev`, `homolog`, `prod` ou `pytest` |
| `DATABASE_URL` | vazio | Vazio = Postgres interno do compose |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | vazio | Endpoint vazio = MinIO interno |
| `OPENROUTER_API_KEY`, `LLM_MODEL`, `VISION_MODEL`, `JEV_MODEL` | como hoje | Mantidas |
| `TRANSCRICAO_API_KEY`, `TRANSCRICAO_MODELO` | vazio | Transcrição de áudio |
| `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | vazio | Obrigatórias fora de `pytest` |
| `WHATSAPP_NUMEROS` | vazio | `phone_number_id` ativos, separados por vírgula |
| `WHATSAPP_GRAPH_URL` | `https://graph.facebook.com/v23.0` | Aponta para o simulador em dev |
| `GRANATECH_BASE_URL` | api-dev | Aponta para o simulador em dev |
| `GRANATECH_CHAVE_API`, `GRANATECH_WEBHOOK_TOKEN` | vazio | Obrigatórias com a Granatech ligada |
| `GRANATECH_ATIVO` | `false` | Liga o ramo CLT |
| `GRANATECH_PROPOSTA_ATIVA` | `false` | Liga a criação automática de proposta |
| `GRANATECH_TETO_LIBERADO` | `6999` | Teto MEX |
| `GRANATECH_COTA_MENSAL` | `500` | Teto de consultas no mês |
| `GRANATECH_COTA_DIARIA` | `20` | Limite diário |
| `GRANATECH_REAPROVEITAR_DIAS` | `30` | Janela de reaproveitamento por CPF |
| `GRANATECH_TIPO_EMPREGADOR` | `1` | Pendente de confirmação |
| `PAINEL_DOMINIO`, `DOMINIO_PUBLICO` | vazio | CORS, cookies e links curtos |
| `SESSAO_SEGREDO` | vazio | Assinatura de sessão; obrigatória |
| `RETENCAO_CONVERSA_DIAS`, `RETENCAO_DOCUMENTOS_DIAS` | `365` | Para quem não contratou |

**Compose**

- Serviços: `migrate` (roda e termina), `api`, `worker`, `painel`, e opcionais `postgres` e `minio`.
- `COMPOSE_PROFILES=postgres,minio` no `.env` sobe os internos; sem eles, `DATABASE_URL` e `S3_ENDPOINT` são obrigatórias. A aplicação valida essa combinação na subida.
- `api` e `worker` dependem de `migrate` com `service_completed_successfully`; healthcheck em `/health`.
- `compose.yaml` (Dokploy): sem `ports`, sem `container_name`, só volumes nomeados, limites de CPU e memória.
- `compose.override.yaml` (local): portas, `simuladores/granatech` e `simuladores/meta`, e as URLs da Granatech e da Graph apontando para eles.

## Testes, definição de pronto e forma de trabalho

Uma fase só está pronta quando os testes passam, os critérios de aceite foram demonstrados e a documentação foi atualizada.

**Testes**

- Unitários sem rede para regras, triagem, idade × prazo, regra do SIM, teto, escolha de produto, normalização e mapa de status.
- Integração com Postgres, MinIO e simuladores subidos pelo compose (ou `testcontainers`), cobrindo as jornadas da Fase 5 e da Fase 6 ponta a ponta.
- Concorrência: dois turnos da mesma conversa em paralelo não se sobrepõem.
- Os testes existentes do Saturday continuam passando.

**Dados do simulador da Granatech** (respostas reais da dev, sem dados pessoais reais):

- CPF de teste `00189004967` (a dev também gera CPFs válidos em `GET /api-consignado/v1/tools/cpf?digitos=001`).
- Consulta criada com `status: AWAITING_CLIENT_AUTHORIZATION` e `link_termo_consentimento`; termo devolve `201 {"success": true, "message": "Termo de consentimento criado com sucesso"}`; o detalhe fica pronto cerca de 8 s depois.
- Detalhe: `pessoa_natural` com 36 anos e nascimento 1990-05-15; duas margens de R$ 1.500 (Prime Tech LTDA e EMPREGADOR MOCK LTDA); produtos AA17, AA25, AAA36 e AAA48, todos a 4% a.m., com seguro.
- Simulação AAA36, 36 × R$ 300: liberado R$ 4.619,53, IOF R$ 175,28, seguro R$ 503,32 (`SM-100000721-6`), financiado R$ 5.298,13, dívida R$ 10.800, CET 4,9848% a.m., processadora `BMP_MOCK`; só o bloco com seguro.
- O simulador permite disparar cada evento de consulta e de proposta, duplicar e inverter a ordem de eventos, devolver 401, 500 e timeout.

**Forma de trabalho**

- Antes de codar cada fase, envie o plano pelo Plannotator e espere a aprovação.
- Commits pequenos, mensagens em português no imperativo; uma fase termina com todos os testes verdes.
- Comentários e textos em português, no estilo do código atual.
- Pendência da Granatech vira `TODO(granatech): <pergunta>` e fica atrás de flag; liste todas no fim da fase.
- Nunca rode comandos que falem com produção (Granatech, Meta, Dokploy) nem leia arquivos `.env` reais; use o `.env.example`.
- Ao final de cada fase, atualize o `README.md` e o `docs/` com o que mudou e como rodar.
- Em dúvida entre duas interpretações, pergunte em vez de escolher.
