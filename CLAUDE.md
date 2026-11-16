# CLAUDE.md

O contrato do projeto (regras inegociáveis, ponteiros da especificação, comandos
e forma de trabalho) está no `AGENTS.md`, importado abaixo. Este arquivo só
acrescenta as worktrees e o mapa do código.

@AGENTS.md

## Worktrees

Uma worktree por tarefa, em `.claude/worktrees/<nome>` (`claude --worktree <nome>`). O `.worktreeinclude` copia o `.env` para ela; o resto se monta
dentro da worktree com `infra/worktree_montar.sh` (`painel` como argumento, se
for mexer no painel): `.venv` próprio e o banco `saturday_test_<nome>`.

- Os testes de Postgres apagam e recriam as tabelas: cada worktree usa o seu
  banco (`SATURDAY_TEST_DATABASE_URL=.../saturday_test_<nome>`), nunca o
  `saturday_test` de outra sessão rodando ao mesmo tempo.
- O compose local publica portas fixas: só uma worktree sobe o compose por vez.
- Ao terminar, da raiz do checkout principal: `infra/worktree_entregar.sh <nome>`
  faz o fast-forward na `main` (`git rebase main` antes, na worktree, se a
  `main` andou), o push, remove a worktree, o ramo e o banco dela e espera o CI.
- Na sessão presa à worktree, cada chamada leva um `git` simples. Comando
  composto com subshell em segundo plano e o `eval` do `agent-browser` são
  recusados: escreva o arquivo com Write/Edit e rode o script.

## Painel no navegador

Para ver telas rodando, `infra/painel_local.sh` sobe a API (banco
`saturday_painel_dev`, segredos fictícios) e o Vite em `:5173`;
`infra/painel_local.sh seed` cria antes o gestor `gestor@exemplo.test` (a senha
sai no fim do seed, ou vem de `PAINEL_LOCAL_SENHA`), conversas nas três
situações, uma com imagem, PDF e arquivo sem prévia num S3 local, e a conversa
CLT com humano, ficha preenchida e consulta parada (`infra/painel_seed.py`),
mais um alerta e um turno (`infra/painel_seed.sql`).
`infra/painel_prints.sh <pasta> <caminho>...` grava cada tela em desktop claro,
desktop escuro e celular, para o relatório de antes e depois. A revisão de um diff
do painel segue o `CODING_STANDARDS.md`.

## Arquitetura (o que exige ler vários arquivos)

**Duas entradas, mesma montagem.** `saturday` (API, `web/application.py`) e
`saturday-worker` (`worker.py`) montam as mesmas dependências por
`web/composicao.py` (`criar_servico`, `criar_checkpointer`,
`criar_canal_whatsapp`). Ao adicionar um cliente ou canal, ligue-o ali para que
os dois processos o recebam. `web/lifespan.py` cuida só de abrir e fechar.

**Caminho de uma mensagem do WhatsApp:**

1. `web/api/whatsapp.py` valida a assinatura, grava em `eventos_recebidos`
   (`dados/eventos.py`, deduplicado por `wamid`) e responde 200.
2. O worker, em um único laço, chama `jobs/eventos.processar` (evento → turno ou
   atualização de status) e `jobs/outbox.drenar` (entrega).
3. `canais/whatsapp/entrada.py` normaliza o evento (mídia para o S3,
   transcrição de áudio) em um `ChatRequest` e chama `AgentService`.
4. `agent/service.py` é o orquestrador: abre a sessão, pega
   `pg_advisory_xact_lock` da conversa (`dados/trava.py`) e trata `message_id`
   repetido, silêncio com humano, devolução à IA (`devolver`), retenção e poda
   de checkpoints. Quem roda o
   grafo e fecha o turno é `agent/turno.py` (`Turnos.de_cliente` e
   `Turnos.de_sistema`): trilha, handoff e a resposta em `mensagens` e no
   `outbox` **na mesma transação**. O que vai para o banco passa pelo
   `RegistroPostgres`; não há modo sem banco (decisão 0022).
5. `jobs/outbox.py` entrega por `EntregadorPorCanal` (`whatsapp` ou `webhook`).
   O canal só **classifica** o resultado (`ok`, `temporario`,
   `temporario_incerto`, `permanente`, `janela_fechada`); reagendar é só do
   outbox — ver `docs/decisoes/0001-outbox-dono-do-reagendamento.md`. Não
   coloque retry dentro de um canal. As chaves do `payload` de WhatsApp só
   existem em `Envio` (`canais/base.py`): quem enfileira usa `para_payload`,
   quem entrega usa `do_payload`. O que o painel pode mandar por cada canal
   (janela e modelo só na Meta, decisão 0009) sai de `painel/canal.py`: não
   compare `canal` em outro lugar para decidir envio.

O `POST /chat` (contrato HTTP antigo, documentado em `apps/core/README.md`) usa o
mesmo `AgentService`: com `SATURDAY_WEBHOOK_URL` responde 202 e a resposta sai
pelo outbox; sem ela, volta na própria requisição.

**Grafo (`agent/`).** `graph.py` monta o `StateGraph`; `nodes.py` tem os nós,
`routing.py` as decisões de aresta (determinísticas), `state.py` o estado,
`context.py` os clientes injetados (`jev`, `llm`, `anexos`) e `textos.py` os
textos fixos. São dois ramos: INSS → C6, com regras e cálculos em
`portabilidade/` (`hiscon.py` lê o extrato, `calculo.py` e `regras.py` decidem),
e CLT em `agent/clt/` (mapa em `docs/clt.md`).
O estado guarda só a chave do anexo no storage, nunca o conteúdo.

**IA (`services/`).** `jev.py` é o classificador de intenção/público; `llm.py`
responde dúvidas ancoradas na FAQ (`faq.py`); `anexos.py` lê foto/PDF por modelo
de visão; tudo via OpenRouter. Os testes trocam esses clientes por falsos em
`tests/conftest.py` (`resultado_jev`, `FakeJev`, etc.) — reaproveite-os.

**Dados (`dados/`).** SQLAlchemy em `modelos.py`, consultas em
`repositorios.py`, sessão em `sessao.py`. O estado de atendimento só muda por
`atendimento.py`, que abre e resolve os alertas de cada mudança (decisão 0021). Migrações Alembic ficam em
`apps/core/migrations/` (não na raiz); toda mudança em `modelos.py` precisa de
uma migração nova.

**Configuração.** `settings.py` (`pydantic-settings`, prefixo `SATURDAY_`);
`validar_para_subir()` derruba a subida se faltar segredo obrigatório no
ambiente. Variável nova entra também no `.env.example`.

## Agent skills

### Issue tracker

Issues e specs vivem nas GitHub Issues de `Carlos-eduedu/saturday`, via `gh`. Ver `docs/agents/issue-tracker.md`.

### Triage labels

Os cinco rótulos padrão (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). Ver `docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `GLOSSARY.md` na raiz (criado sob demanda) e decisões em `docs/decisoes/`. Ver `docs/agents/domain.md`.
