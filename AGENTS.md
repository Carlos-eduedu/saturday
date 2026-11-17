# AGENTS.md — Saturday (piloto Granatech)

Contrato de trabalho do repositório. O Saturday é o agente de atendimento
autônomo da MEX no WhatsApp, com dois ramos: portabilidade INSS → C6 e Crédito
do Trabalhador (CLT) pela Granatech, o piloto. O ramo INSS e os testes
existentes continuam funcionando em toda mudança.

## Regras inegociáveis

Se uma tarefa parecer exigir quebrar uma destas regras, pare e pergunte.

1. **Auto-suficiência:** o Saturday não chama, não lê e não escreve em nenhum sistema da MEX (CRM, Supabase do Deu Plim, hub `mex-granatech-api`). Só parceiros externos: Meta, Granatech, C6, BrasilAPI, OpenRouter. Única exceção: o motor de consultas do iCred, com chave própria e sem o escopo `operacao` (decisão 0027).
2. **Decisões em código:** triagem, consentimento, regras de banco, cálculos, escolha de produto e transições de estado são determinísticos e testados. O LLM só classifica intenção e responde dúvidas ancoradas na FAQ; nunca escreve números, valores ou condições.
3. **Consentimento do cliente:** nenhuma consulta e nenhuma proposta sem um "SIM" explícito do próprio cliente, conferido em código, com prova gravada. Nunca simule aceite com dados de aparelho inventados.
4. **Proposta nunca repetida automaticamente:** `POST` de proposta não tem retry. Grave a intenção antes; em resultado incerto (timeout, 5xx), procure a proposta na listagem antes de qualquer nova tentativa.
5. **Cota da Granatech:** nunca abra consulta sem passar pela triagem, pelo consentimento e pelo controle de cota (teto mensal, limite diário, reaproveitamento por CPF).
6. **Teto de R$ 6.999 (CLT):** no Crédito do Trabalhador, nenhuma simulação é apresentada e nenhuma proposta é criada com valor liberado acima disso. O ramo INSS não tem teto (decisão 0027).
7. **Seguro:** toda oferta com seguro diz que ele está incluído, o valor e que é opcional.
8. **Segredos:** só por variável de ambiente. O serviço não sobe se faltar um obrigatório. Nada de chave, token ou senha em código, teste, fixture, log ou commit.
9. **Dados pessoais:** CPF, e-mail, telefone, nome da mãe e endereço mascarados em logs. O log de chamadas externas guarda só metadados (rota, status, tempo, IDs). Mídia e documentos só em storage privado, nunca em base64 no estado do grafo.
10. **Webhooks:** gravar, responder 200 rápido e processar no worker. Assinatura validada quando o parceiro assina (Meta, em tempo constante); token longo quando não assina. Processamento idempotente e sem regressão de estado após status final.
11. **Sem chamadas reais em teste:** testes e desenvolvimento usam os simuladores. Nunca chame a Granatech de produção nem envie WhatsApp real fora do ambiente de produção.
12. **Não invente contratos de API:** use só os campos e rotas descritos na especificação. O que estiver marcado como pendente fica atrás de flag e com `TODO(granatech)`.

**Fora do escopo:** Finqia, V8, Presença, C6 CLT, Facta e demais bancos; FGTS;
NovaVida; qualquer dependência do CRM da MEX.

Contrato novo e refinanciamento INSS no C6, pela API do banco, entraram no
escopo pela decisão 0026. O iCred (INSS), pelo motor de consultas da MEX, entrou
pela decisão 0027; o que se sabe do motor está em `docs/icred.md`.

## Especificação

A fonte de verdade é o documento
`Prompt para o Pi implementação do Saturday (piloto Granatech).md`, na raiz.
Leia a seção da área antes de mexer nela. Um desvio registrado em
`docs/decisoes/` vence a especificação: liste a pasta (o nome do arquivo diz o
tema) e leia os que tocam a área.

| Ao mexer em | Seção do documento | Como está hoje |
| --- | --- | --- |
| Cliente, cota, webhook ou simulador da Granatech | "Especificação: API Granatech" e "Dados do simulador da Granatech" (em "Testes, definição de pronto e forma de trabalho") | `docs/granatech.md` |
| Ramo CLT: etapas, triagem, consentimento, oferta, proposta, mensagens fixas | "Especificação: jornada CLT, triagem e mensagens" | `docs/clt.md` |
| Canal WhatsApp da Meta ou painel | "Especificação: WhatsApp e painel" | `apps/core/README.md` |
| Canal Evolution | fora do documento | `docs/evolution.md` |
| iCred (motor de consultas) | fora do documento; decisão 0027 | `docs/icred.md` |
| Variável de ambiente ou compose | "Variáveis de ambiente e compose" | `.env.example`, `docs/deploy.md` |
| Pasta, módulo ou interface nova | "Arquitetura alvo e estrutura do monorepo" | `docs/estado.md` |
| Fechar ou retomar uma fase | "Fases de implementação" | `docs/estado.md` |

## Como rodar

O workspace `uv` tem um único `uv.lock` e um único `.venv` na raiz (membros:
`apps/core` e `simuladores`). Lint, tipos e testes rodam de dentro do membro; o
servidor roda da raiz, porque o `.env` é lido do diretório atual.

```bash
cd apps/core
uv sync --locked
uv run ruff check --fix && uv run ruff format         # corrige estilo
uv run mypy                                           # strict, só src/saturday
uv run pytest -q                                      # sem o Postgres de teste, pula os do agente e os de banco
uv run pytest tests/test_whatsapp.py::nome_do_teste   # um teste
uv run pytest -k janela -q                            # por nome

cd simuladores && uv run ruff check && uv run mypy    # o CI também cobre os simuladores
```

Testes de Postgres, em um banco **descartável** (o nome precisa conter `test`:
os fixtures apagam e recriam as tabelas). Rode-os antes de dar uma fase por pronta:

```bash
docker compose --profile postgres up -d postgres
docker exec saturday-postgres-1 createdb -U saturday saturday_test
SATURDAY_TEST_DATABASE_URL='postgresql://saturday:saturday@127.0.0.1:5432/saturday_test' \
  uv run pytest -q
```

Servidor local e compose, da raiz:

```bash
uv run --project apps/core alembic -c apps/core/alembic.ini upgrade head
uv run --project apps/core saturday               # API em http://localhost:8000
uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100
docker compose --profile postgres --profile s3 up --build
```

- `pytest` roda com `filterwarnings = error`: qualquer warning novo quebra a suíte.
- Testes marcados `jev` chamam o classificador de verdade e são pulados sem
  `SATURDAY_OPENROUTER_API_KEY`.
- Com `environment == "pytest"` o checkpointer é `InMemorySaver` e o storage é
  `MemoriaStorage` (também sem `S3_BUCKET`). O banco não tem versão em memória:
  o `AgentService` exige o Postgres também nos testes (decisão 0022), então
  quem mexe em `agent/` roda com `SATURDAY_TEST_DATABASE_URL`.
- O Postgres de teste precisa do pgvector (decisão 0017): a imagem é
  `pgvector/pgvector:pg17`; um container antigo em `postgres:17-alpine` falha em
  `CREATE EXTENSION`.
- Há `.env` e `.env.backup` reais na raiz: use o `.env.example` como referência.
- Hook de pre-commit versionado em `.githooks/` (formatação e lint do que vai no
  commit). Ligue uma vez por clone: `git config core.hooksPath .githooks`.
- `compose.yaml` tem a forma de deploy (Dokploy: sem portas, volumes nomeados,
  limites de recurso); `compose.override.yaml` é carregado sozinho e publica as
  portas no ambiente local.
- As variáveis levam o prefixo `SATURDAY_`. Em `homolog` e `prod` o serviço não
  sobe sem os segredos obrigatórios.

## Forma de trabalho

- Antes de codar uma mudança de comportamento ou uma refatoração de mais de um arquivo, envie o plano pelo Plannotator e espere a aprovação.
- Mudança de UX/UI: envie pelo Plannotator um relatório com prints ou vídeo curto de antes e depois; o commit só sai com a aprovação.
- Uma fase só está pronta quando os testes passam, os critérios de aceite foram
  demonstrados e a documentação foi atualizada (`README.md`, `docs/` e
  `docs/estado.md`).
- Commits pequenos, mensagens em português no imperativo.
- Comentários e textos em português, no estilo do código atual.
- Pendência da Granatech vira `TODO(granatech): <pergunta>` e fica atrás de flag; liste todas no fim da fase.
- Desvio consciente da especificação vira um registro novo em `docs/decisoes/NNNN-*.md`.
- Nunca rode comandos que falem com produção da Granatech ou da Meta nem leia arquivos `.env` reais; use o `.env.example`.
- Dokploy: leitura livre (listar e consultar projetos, ambientes, serviços, deploys e logs); qualquer alteração (criar, editar, deploy, parar, apagar) só depois de confirmação explícita do usuário para aquela ação, com alvo por nome e ID. Nunca leia nem exiba o token do painel nem os valores de variáveis de ambiente dos serviços (docs/decisoes/0005).
- Em dúvida entre duas interpretações, pergunte em vez de escolher.
