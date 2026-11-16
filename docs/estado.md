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
  contador de cota;
  tempo real por `pg_notify` + SSE. Depois, fora das fases: aba Usuários (só
  gestor) para cadastrar, editar, redefinir senha, desbloquear, desativar e
  reativar; excluir é desativar (docs/decisoes/0012). Aba Granatech para
  todos (consultas, propostas, linha do tempo, cota) com ações só do gestor:
  reconciliar, reenviar link, cancelar, corrigir conta e atualizar detalhe;
  abrir consulta, simular e criar proposta ficam só na conversa
  (docs/decisoes/0013).
- **Fase 4 concluída:** cliente Granatech em `bancos/granatech/` (token em cache,
  retry só em GET, normalização em `Decimal`, teto, proposta única com
  reconciliação pela listagem), cota com trava e alerta a 80%, reaproveitamento
  por CPF (local e depois remoto), tabelas `consultas_granatech` e
  `propostas_granatech`, webhook `/webhooks/granatech` sempre no ar (503 sem
  token), status aplicado no worker sem regredir, alerta de consulta parada há
  15 min e o simulador em `simuladores/granatech/`. Sem interface `Banco` até o
  segundo banco (docs/decisoes/0004). Detalhes e pendências em `docs/granatech.md`.
- **Fase 5 concluída:** ramo CLT em `agent/clt/` até a oferta, com triagem antes
  da identificação (docs/decisoes/0007), BrasilAPI com cache em `empresas_cnpj`
  e sem `FonteCadastral` (docs/decisoes/0006), prova do SIM antes de qualquer
  consulta, turno de sistema (`AgentService.continuar`) disparado pelos eventos
  da consulta, recontato por cota esgotada (tabela `recontatos`), até 5 novas
  simulações depois da oferta e mensagens em `conhecimento/clt/mensagens.yaml`.
  O aceite vai para handoff (`aceite_clt`) até a Fase 6. Ver `docs/clt.md`.
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
  reagendamento só no outbox (6 tentativas, jitter, incerto com 1 retry) e
  `docs/` com as decisões registradas em `docs/decisoes/`.
- Canal Evolution (fora das fases, docs/decisoes/0009): números de WhatsApp Web
  pela Evolution API v2.3.7 (Baileys), canal `evolution` ao lado de `whatsapp`,
  sem janela nem modelos, instância própria no profile `evolution` do compose,
  webhook pela rede interna com token, simulador em `simuladores/evolution/` e
  tudo atrás de `SATURDAY_EVOLUTION_ATIVO`. Instâncias geridas pela tela Canais
  do painel, só gestor, com telefone fixado e alerta de queda
  (docs/decisoes/0010); webhook conferido e configurações da instância
  ajustadas pelo painel (docs/decisoes/0011). Ver `docs/evolution.md`.
- `migrations/` fica em `apps/core/migrations/`, não na raiz: as migrações
  descrevem os modelos daquele pacote e precisam do ambiente `uv` dele para
  importar. Desvio consciente da árvore desenhada na especificação.
- Em `homolog` e `prod` o serviço não sobe sem `SATURDAY_API_KEY`; em `dev` e
  `pytest` a ausência só gera aviso no log.
- O ramo INSS → C6 (`apps/core/src/saturday/portabilidade/` e
  `apps/core/src/saturday/agent/`) deve continuar funcionando em toda fase.
- Pendência desta fase: `minio/minio` não está mais publicável nos registries
  oficiais neste ambiente; o `S3Storage` está coberto por teste com cliente
  falso, mas o caminho real contra MinIO não foi exercitado aqui.
