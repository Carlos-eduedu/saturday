# Estado do projeto por fase

O que cada fase entregou e o que segue pendente. Atualize ao fechar uma fase ou
uma entrega fora das fases.

- **Fase 0 concluída:** monorepo, compose, CI e este arquivo.
- **Fase 1 concluída:** Postgres com SQLAlchemy e Alembic, checkpointer
  `PostgresSaver`, trava por conversa com `pg_advisory_xact_lock`, outbox
  transacional com worker e backoff, storage S3 para anexos (o estado guarda só a
  chave) e as quatro correções do ramo INSS.
- **Fase 2 concluída:** webhook da Meta (verificação, assinatura em tempo
  constante, deduplicação por `wamid`), fila de eventos processada no worker,
  mídia em dois passos com limite de 50 MB, transcrição de áudio, status de
  entrega, texto dividido em até cinco partes, janela de 24 h com modelo fora
  dela, as sete mensagens do piloto e o simulador da Meta. A suíte tem 185 testes.
- **Fase 3 concluída:** API admin `/admin/*` e painel em `apps/painel/` (React,
  Vite, TS, servido por nginx com proxy na mesma origem); login argon2id com
  bloqueio, sessão no banco e CSRF; estado de atendimento (`ia`, `handoff`,
  `assumida`) em `conversas` (docs/decisoes/0003); assumir, devolver, transferir
  e responder; ficha mascarada com revelar auditado; alertas (o de handoff se
  resolve ao assumir ou devolver e volta com o desfazer, docs/decisoes/0018;
  a liberação por prazo e o `/release` também o resolvem, sem usuário);
  devolver é uma operação só (`AgentService.devolver`): banco, alertas,
  auditoria e checkpoint sob a trava, com o checkpoint zerado antes do commit;
  cada fala da IA guarda o turno e a chave da mensagem fixa (0018);
  a fala com reais é conferida contra a oferta vigente da conversa, de
  qualquer ramo (CLT, contrato novo no C6, portabilidade ou iCred): a última
  oferta mostrada ao cliente, achada pela chave da fala
  (`ofertas_da_conversa`, em `agent/service.py`), que a ficha entrega com os
  valores prontos; a fala fixa de oferta é conferida contra a oferta do
  próprio ramo, e a oferta recusada segue na conferência, marcada "recusada"
  no cartão (docs/c6.md, "O que o atendente vê");
  contador de cota;
  tempo real por `pg_notify` + SSE. Depois, fora das fases: aba Usuários (só
  gestor) para cadastrar, editar, redefinir senha, desbloquear, desativar e
  reativar; excluir é desativar (docs/decisoes/0012). Cada pessoa troca a
  própria senha em "Seu perfil", e a senha definida pelo gestor exige troca
  no primeiro acesso: até lá o servidor só deixa trocar a senha e sair
  (docs/decisoes/0030). Aba Granatech para
  todos (consultas, propostas, linha do tempo, cota) com ações só do gestor:
  reconciliar, reenviar link, cancelar, corrigir conta e atualizar detalhe;
  abrir consulta, simular e criar proposta ficam só na conversa
  (docs/decisoes/0013).
  Aba Membros para todos: lista da equipe e página do membro
  (`/membros/:id`) com estado, carga, atividade de 7 dias, últimas ações e a
  gestão do gestor; o servidor decide o que cada um vê (docs/decisoes/0023).
  Perfil e Acesso do membro abrem em modal; o gestor liga para um membro os
  dados sem máscara em todo o painel, com auditoria por ficha aberta
  (docs/decisoes/0037).
  Aba Operação com o funil para o gestor (`GET /admin/funil`): por produto,
  as conversas iniciadas no período que chegaram a cada etapa (iniciadas, SIM,
  oferta, aceite, proposta criada, pago), com a taxa de passagem calculada no
  servidor e "não se aplica" na etapa que o produto não tem; fontes e regra
  de período (coorte da conversa iniciada) em docs/decisoes/0031.
  Comandos de chat do membro testador: `/ajuda`, `/estado`, `/reiniciar`,
  `/humano`, `/devolver` e, só com a Granatech simulada, `/ir` e `/cenario`; o
  simulador manda sozinho o resultado da consulta aberta com cenário
  (docs/decisoes/0024).
- **Sentry nos erros do backend:** API e worker mandam ao projeto `saturday`
  todo `logger.error`/`exception`, mascarado e sem variáveis locais, corpos,
  integrações de IA nem tracing; liga com `SATURDAY_SENTRY_DSN`
  (docs/decisoes/0038).
- **Fase 4 concluída:** cliente Granatech em `bancos/granatech/` (token em cache,
  retry só em GET, normalização em `Decimal`, teto, proposta única com
  reconciliação pela listagem), cota com trava e alerta a 80%, reaproveitamento
  por CPF (local e depois remoto), tabelas `consultas_granatech` e
  `propostas_granatech`, webhook `/webhooks/granatech` sempre no ar (503 sem
  token), status aplicado no worker sem regredir, alerta de consulta parada há
  15 min e o simulador em `simuladores/granatech/`. Sem interface `Banco` até o
  segundo banco (docs/decisoes/0004). Detalhes e pendências em `docs/granatech.md`.
- **C6, contrato novo e refinanciamento INSS (decisão 0026), em andamento:**
  feito o cliente em `bancos/c6/` (token, simulação, inclusão, consulta e link
  de formalização), o simulador em `simuladores/c6/` (no compose local, porta
  8500, com saúde e rotas de administração) e o SIM do cliente antes
  da simulação, com prova gravada (atrás de `SATURDAY_C6_ATIVO`). Depois do SIM, o
  agente simula e oferece o contrato novo; o aceite vai para um atendente, que
  vê as condições na conversa do painel (seção "Contrato novo no C6"). As
  regras do produto estão na aba Operação e o C6 da aba Bancos descreve o
  contrato novo. Faltam refinanciamento, digitação e acompanhamento da
  proposta. Detalhes e pendências em `docs/c6.md`.
- **Integração da Granatech para o APP MEX (decisões 0035 e 0036), concluída:**
  as quatro fases: tokens com escopo na página Integrações (só
  gestor, só o hash no banco), proxy de leitura e de escrita em
  `/integracao/granatech/api-consignado/v1/` (crus, menos o CPF, mascarado),
  com cota e reaproveitamento, teto conferido pela simulação repassada,
  proposta sem retry e 409 em item de outro dono; cota e revelar CPF em
  `/integracao/`; aviso de status por webhook assinado, pelo outbox, para a
  integração dona; homologação (rodadas da 0014) pedida pela integração. Detalhes em
  `docs/granatech.md`, "Integração (APP MEX)".
- **Fase 5 concluída:** ramo CLT em `agent/clt/` até a oferta, com triagem antes
  da identificação (docs/decisoes/0007), BrasilAPI com cache em `empresas_cnpj`
  e sem `FonteCadastral` (docs/decisoes/0006), prova do SIM antes de qualquer
  consulta, turno de sistema (`AgentService.continuar`) disparado pelos eventos
  da consulta, recontato por cota esgotada (tabela `recontatos`), até 5 novas
  simulações depois da oferta e mensagens em `conhecimento/clt/mensagens.yaml`.
  Com `SATURDAY_GRANATECH_PROPOSTA_ATIVA` desligada, o aceite vai para handoff
  (`aceite_clt`); ligada, segue para a proposta da Fase 6. Ver `docs/clt.md`.
- **Fase 6 concluída:** dados da proposta antes do SIM (docs/decisoes/0008),
  aceite com prova `proposta`, criação única com reconciliação e dados do
  tomador, pós-venda por turno de sistema com o modelo certo fora da janela,
  link curto `/l/{codigo}` resolvido no clique (`SATURDAY_DOMINIO_PUBLICO`),
  falha de pagamento com PATCH atrás de `SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO`
  e recontato por tempo de casa com opt-in (`conversas.marketing`). Ver
  `docs/clt.md`.
- **Fase 7 (código e guia concluídos):** guia de deploy com ambiente do zero,
  backup e restauração (`docs/deploy.md`), teste de restauração
  (`infra/testar_restauracao.sh`), evidências da homologação Granatech
  (seção Homologação da aba Granatech, rodada pelo worker; o script saiu,
  docs/decisoes/0014) e
  o material da Granatech sem segredos em `docs/granatech-homologacao/`. O
  homolog foi montado no Dokploy seguindo o guia (rede, Postgres, stack,
  variáveis sem segredo e domínios). **Pendentes:** bucket S3 de anexos e número
  de teste da Meta do homolog, segredos e primeiro deploy do homolog, destino S3
  dos backups e a troca do webhook da Granatech para o homolog. `regras/` nasce
  na fase que colocar nele o primeiro arquivo real.
- Fora das fases, o repositório já tem: workspace `uv` único (um lock e um
  venv na raiz), healthcheck próprio por serviço (a API responde `/health`, o
  worker verifica banco e batimento do laço, o migrate não tem), entrega com
  reagendamento só no outbox (8 tentativas, jitter, incerto com 1 retry) e
  `docs/` com as decisões registradas em `docs/decisoes/`.
- Canal Evolution (fora das fases, docs/decisoes/0009): números de WhatsApp Web
  pela Evolution API v2.3.7 (Baileys), canal `evolution` ao lado de `whatsapp`,
  sem janela nem modelos, instância própria no profile `evolution` do compose,
  webhook pela rede interna com token, simulador em `simuladores/evolution/` e
  tudo atrás de `SATURDAY_EVOLUTION_ATIVO`. Instâncias geridas pela tela Canais
  do painel, só gestor, com telefone fixado e alerta de queda
  (docs/decisoes/0010); webhook conferido e configurações da instância
  ajustadas pelo painel (docs/decisoes/0011). Ver `docs/evolution.md`.
- Meta na tela Canais (fora das fases, issue 31, docs/decisoes/0032): cada
  número mostra o número exibido (mascarado) e a qualidade, lidos na Graph por
  `GET /{phone_number_id}` e guardados 60 s em memória; a Meta fora do ar vira
  um aviso na linha do número. Gerir números da Meta continua fora do painel.
  Pendente, passo de uma pessoa: conferir legenda e nome de arquivo num envio
  real (roteiro em `docs/meta.md`).
- iCred, fase 1 (fora das fases, docs/decisoes/0027): no ramo INSS, depois do
  extrato, o agente pede o SIM e o CPF, consulta o motor do iCred, apresenta o
  pacote e colhe o aceite com prova; o atendente grava a proposta. Webhook
  assinado em `/webhooks/icred`, simulador em `simuladores/icred/` e tudo atrás
  de `SATURDAY_ICRED_ATIVO`. **Pendentes:** cadastro da aplicação do Saturday no
  motor (chave, webhook e segredo), a fase 2
  (gravação pelo agente, condicionada aos pedidos ao motor listados na 0027) e
  duas perguntas em aberto: seguro e CET da oferta (`TODO(icred)` em
  `agent/icred/textos.py` e na seção Pendências da 0027) e o que o cliente faz
  no link de assinatura (seção Pendências da 0027 e "Continua sem resposta" em
  `docs/icred.md`, sem `TODO` no código). Com o C6 ligado junto, o pedido de
  SIM do iCred vem depois do C6 com abertura própria, e um SIM só vale para
  o último pedido mostrado: extrato novo cancela o pedido do iCred sem resposta,
  extrato de outro titular descarta consulta e oferta do titular anterior, e
  o SIM que não responde à última mensagem do agente refaz o pedido, também só
  com o iCred ligado (issue 22). Sobras fechadas na issue 42: CPF digitado
  diferente do extrato não é consultado (na segunda vez, handoff
  `icred_cpf_divergente`); depois da devolução à IA o "sim" não aceita pedido
  nem oferta de antes do atendente; no pedido de CPF a afirmação curta ("ok")
  recebe o pedido de novo sem ir à triagem; e a ficha mostra como desistida a consulta do titular descartado. Ver
  `docs/icred.md`.
- O SIM só vale para o último pedido que o cliente viu, em todos os ramos
  (issue 44, docs/decisoes/0033): no CLT, depois da devolução pelo atendente, o
  "sim" não grava prova, não abre consulta, não aceita a oferta nem cria a
  proposta; a etapa mostra o pedido de novo e só o "sim" seguinte vale
  (`_refazer_pedido`, em `agent/clt/nos.py`). O "Desfazer" do painel deixa a
  mesma marca quando o atendente escreveu ao cliente antes de desfazer.
  Fechado na issue 45 (nota de 2026-11-18 na decisão 0033): no CLT a guarda
  vale até o pedido da etapa aparecer de novo depois da marca, qualquer que
  seja a fala da IA no meio (`falas_desde_o_atendimento`, em `agent/state.py`);
  e a marca só existe quando um atendente escreveu ao cliente desde que a
  conversa saiu da IA (`AgentService._liberar_handoff`, com o id da última fala
  contada em `fala_atendente`, no estado): prazo vencido, `/release` e devolver
  sem ter escrito não refazem pedido, no CLT e no iCred. Issue 46: anexo no
  resumo da proposta recebe o resumo, não o pedido da consulta.
- `migrations/` fica em `apps/core/migrations/`, não na raiz: as migrações
  descrevem os modelos daquele pacote e precisam do ambiente `uv` dele para
  importar. Desvio consciente da árvore desenhada na especificação.
- Em `homolog` e `prod` o serviço não sobe sem `SATURDAY_API_KEY`; em `dev` e
  `pytest` a ausência só gera aviso no log.
- O ramo INSS → C6 (`apps/core/src/saturday/portabilidade/` e
  `apps/core/src/saturday/agent/`) deve continuar funcionando em toda fase.
- S3 local: a imagem `minio/minio` saiu do Docker Hub, e o compose passou a
  usar o `adobe/s3mock:5.2.3` (serviço e profile `s3`, decisão 0028), o mesmo do
  `infra/painel_local.sh`. Quem tem `COMPOSE_PROFILES=postgres,minio` troca por
  `postgres,s3` e aponta `SATURDAY_S3_ENDPOINT=http://s3:9090`. Conferido em
  2026-11-17: o serviço sobe pelo compose, fica saudável, nasce com o bucket e
  guarda os arquivos no volume depois de reiniciar e de recriar o container; o
  `S3Storage` de produção grava, lê, regrava e apaga contra ele
  (`tests/test_storage_s3_real.py`, pulado sem `SATURDAY_TEST_S3_ENDPOINT`). Não
  conferido: a API e o worker do compose falando com ele, e um bucket externo
  de verdade.
