# Deploy no Dokploy

O Saturday roda no Dokploy da Dynatech (`infra.dynatech.systems`), projeto
`Saturday`, com um ambiente por estágio. Cada ambiente tem o seu stack compose,
o seu Postgres gerenciado pelo Dokploy e o seu bucket S3 externo. Alterar
qualquer coisa no painel segue a regra de `decisoes/0005`.

Para subir um ambiente novo, siga "Ambiente do zero", no fim do guia; as seções
antes dele explicam o porquê de cada passo.

## Ambientes

| | development | homolog | production |
| --- | --- | --- | --- |
| Postgres (Dokploy) | `saturday-postgres-dev` | `saturday-postgres-homolog` | `saturday-postgres-prod` |
| Stack compose | `saturday` | `saturday` | `saturday` |
| Branch e deploy | `main`, automático a cada push | `main`, manual | `main`, manual |
| API (`api`, porta 8000) | `saturday-dev.dynatech.systems` | `saturday-homolog.dynatech.systems` | `saturday.dynatech.systems` |
| Painel (`painel`, porta 80) | `painel-saturday-dev.dynatech.systems` | `painel-saturday-homolog.dynatech.systems` | `painel-saturday.dynatech.systems` |
| `SATURDAY_ENVIRONMENT` | `dev` | `homolog` | `prod` |
| `SATURDAY_IMAGEM_TAG` | `development` | `homolog` | `production` |

A API recebe os webhooks da Meta e da Granatech e o `POST /chat`; o painel é o
nginx que serve o build do Vite e repassa `/admin` para a API na mesma origem.

## Configuração do stack

- Compose path `./compose.yaml`. O `compose.override.yaml` é só local: o Dokploy
  não o carrega, então simuladores e portas publicadas não sobem lá.
- **Isolated deployment ligado.** Os três stacks dividem o servidor; sem
  isolamento, os serviços `api`, `painel` e `migrate` de ambientes diferentes
  ficariam com o mesmo nome na `dokploy-network`.
- `SATURDAY_IMAGEM_TAG` diferente por ambiente, pelo mesmo motivo: com tag
  fixa, o build de um ambiente trocaria a imagem que o outro usa.
- `COMPOSE_PROFILES` vazio: o banco é o Postgres do Dokploy e o storage é um
  bucket externo, então `SATURDAY_DATABASE_URL` e `SATURDAY_S3_*` são
  obrigatórias.
- Domínios pela aba Domains do stack (o Dokploy injeta os labels do Traefik),
  com HTTPS e certificado Let's Encrypt.
- Com `SATURDAY_GRANATECH_PROPOSTA_ATIVA=true`, `SATURDAY_DOMINIO_PUBLICO` é
  obrigatória, e o caminho `/l/` desse domínio precisa chegar à `api` (links
  curtos da biometria, `GET /l/{codigo}`). O botão dos modelos
  `assinatura_pronta` e `assinatura_refazer` na Meta aponta para
  `https://{dominio}/l/{{1}}`.
- Command (aba Advanced), trocando o appName do stack:
  `compose -p <appName> --env-file .env -f ./compose.yaml -f ./compose.dokploy.yaml up -d --build --remove-orphans`.

## Rede do banco

O Postgres gerenciado roda como serviço Swarm, que só entra em rede overlay; o
stack isolado não o enxerga. Por ambiente há uma rede `saturday-<ambiente>-dados`
(overlay, attachable), criada no Dokploy, sincronizada com o Docker e ligada ao
Postgres (Networks do serviço, seguido de deploy do banco).
`compose.dokploy.yaml` liga `migrate`, `api` e `worker` a ela, pelo nome em
`SATURDAY_REDE_DADOS`. O `serviceNetworks` do stack não serve: ele liga os
serviços à rede, mas não a declara no compose, que então é recusado.

## Variáveis

Preenchidas na aba Environment de cada stack, a partir do `.env.example`, mais
`SATURDAY_REDE_DADOS`. O Dokploy grava um `.env` ao lado do compose, que é o
`env_file` dos serviços. Segredos podem ficar nas variáveis do ambiente e ser
referenciados no stack como `${{environment.NOME}}`; sem a referência, não
chegam ao stack. Senha do Postgres só com letras e números: caractere especial
quebra a URL. Em `development` e `homolog`,
`SATURDAY_GRANATECH_PROPOSTA_ATIVA=false` e o WhatsApp nunca aponta para número
real de cliente.

## Ordem de um deploy

1. Postgres do ambiente criado, ligado à rede de dados e com o host interno em
   `SATURDAY_DATABASE_URL`.
2. Conferir o compose final (Preview Compose) antes do primeiro deploy.
3. Deploy. O `migrate` aplica as migrações e termina; `api` e `worker` só sobem
   se ele der certo.
4. Conferir `https://<api>/health`, o login do painel e o log do `worker`.

## Ambiente do zero

Na ordem. Cada passo de escrita no Dokploy (criar, editar, deploy) segue a
`decisoes/0005`. `<amb>` é `dev`, `homolog` ou `prod`.

1. **DNS.** Registros A para a API e o painel (ver "Ambientes") apontando para o
   IP do servidor do Dokploy. Confira com `dig +short <host>` antes de criar os
   domínios: sem o DNS, o certificado não sai.
2. **Rede de dados.** No Dokploy, crie a rede `saturday-<amb>-dados` (overlay,
   attachable) e sincronize com o Docker.
3. **Postgres.** Crie `saturday-postgres-<amb>` (imagem `postgres:17-alpine`,
   banco e usuário `saturday`, senha só com letras e números) no ambiente do
   projeto `Saturday`. Em Networks, ligue-o à rede do passo 2 e faça o deploy do
   banco. Anote o host interno (`appName` do Postgres).
4. **Bucket S3** dos anexos, privado, com versionamento ligado (ver "Backup").
   Gere uma chave de acesso só para esse bucket.
5. **Stack compose** `saturday` no ambiente: provedor GitHub, repositório
   `Carlos-eduedu/saturday`, branch `main`, compose path `./compose.yaml`,
   **Isolated deployment ligado** e o Command de "Configuração do stack" com o
   `appName` do stack. Deploy automático só em `development`.
6. **Variáveis** (aba Environment), a partir do `.env.example`:
   - `SATURDAY_ENVIRONMENT=<dev|homolog|prod>`, `SATURDAY_IMAGEM_TAG` da tabela,
     `SATURDAY_REDE_DADOS=saturday-<amb>-dados`, `COMPOSE_PROFILES=` (vazio);
   - `SATURDAY_DATABASE_URL=postgresql://saturday:<senha>@<appName-do-postgres>:5432/saturday`;
   - `SATURDAY_S3_ENDPOINT`, `SATURDAY_S3_BUCKET`, `SATURDAY_S3_REGIAO`;
   - `SATURDAY_GRANATECH_BASE_URL` (`https://api-dev.granatech.com.br` fora de
     produção), `SATURDAY_GRANATECH_ATIVO=true`,
     `SATURDAY_GRANATECH_PROPOSTA_ATIVA=false` fora de produção;
   - `SATURDAY_WHATSAPP_NUMEROS` (o `phone_number_id` do número do ambiente;
     fora de produção, só número de teste da Meta);
   - `SATURDAY_DOMINIO_PUBLICO` = domínio da API (obrigatória com a proposta
     ligada).

   **Segredos**, preenchidos por quem tem acesso, nunca por agente nem por
   commit: `SATURDAY_API_KEY`, `SATURDAY_SESSAO_SEGREDO`,
   `SATURDAY_OPENROUTER_API_KEY`, `SATURDAY_TRANSCRICAO_API_KEY`,
   `SATURDAY_WHATSAPP_TOKEN`, `SATURDAY_WHATSAPP_APP_SECRET`,
   `SATURDAY_WHATSAPP_VERIFY_TOKEN`, `SATURDAY_GRANATECH_CHAVE_API`,
   `SATURDAY_GRANATECH_WEBHOOK_TOKEN`, `SATURDAY_S3_ACCESS_KEY`,
   `SATURDAY_S3_SECRET_KEY` e a senha dentro de `SATURDAY_DATABASE_URL`. Gere
   `API_KEY`, `SESSAO_SEGREDO`, `VERIFY_TOKEN` e `WEBHOOK_TOKEN` com
   `openssl rand -hex 32`. Em `homolog` e `prod` o serviço não sobe sem eles.
7. **Domínios** (aba Domains do stack): serviço `api`, porta 8000, no host da API
   (cobre `/webhooks/*`, `/chat` e `/l/*`); serviço `painel`, porta 80, no host
   do painel. HTTPS com Let's Encrypt.
8. **Preview Compose** e **deploy**. O `migrate` aplica as migrações e termina;
   `api` e `worker` só sobem se ele der certo.
9. **Conferência:**
   - `curl -f https://<api>/health`;
   - log do `migrate` com `Running upgrade` até a head e saída 0;
   - log do `worker` com `worker_iniciado` e container saudável;
   - primeiro gestor, no terminal do container `api`:
     `saturday criar-usuario --email <email> --perfil gestor`;
   - login no painel.
10. **Webhooks dos parceiros:**
    - Meta: callback `https://<api>/webhooks/whatsapp` com o
      `SATURDAY_WHATSAPP_VERIFY_TOKEN`, assinando o campo `messages`;
    - Granatech: pedir no grupo a troca da rota para
      `https://<api>/webhooks/granatech`, autenticada pelo header
      `x-webhook-token: <SATURDAY_GRANATECH_WEBHOOK_TOKEN>`.
11. **Backup** do Postgres e do bucket (ver "Backup") e um teste de restauração.

## Backup

**Postgres.** Backup nativo do Dokploy, enviado a um destino S3:

1. Settings → S3 Destinations: destino `saturday-backups`, num bucket privado
   só para backups (credenciais só no painel).
2. No Postgres do ambiente, aba Backups: destino `saturday-backups`, prefixo
   `saturday/<amb>/`, cron `0 3 * * *` (diário às 03:00), guardando 14 backups.
3. "Run manual backup" uma vez e confira o arquivo no bucket.

Vale para `development` e `homolog` (e `production` quando existir).

> **Pendente (2026-11-11):** o destino `saturday-backups` ainda não foi criado;
> os backups do Postgres estão desligados até ele existir.

**Storage dos anexos.** Sem código: no bucket de anexos de cada ambiente, ligue o
**versionamento** e uma regra de **ciclo de vida** que expira versões antigas
(não as atuais) depois de 30 dias. Um anexo apagado ou sobrescrito volta
restaurando a versão anterior no console do provedor (ou
`aws s3api list-object-versions` / `copy-object` com o `VersionId`). A retenção
do Saturday apaga a versão atual; a cópia antiga some sozinha em 30 dias.

## Restauração

Teste mensal, e sempre depois de mudar o backup:

1. Baixe o último backup do destino S3 (o arquivo `.sql.gz` do Dokploy).
2. Da raiz do repositório, com Docker: `infra/testar_restauracao.sh <arquivo>`.
   O script restaura num Postgres descartável, compara a versão das migrações
   com a head do repositório e conta as tabelas principais. "Restauração OK" é
   o aceite; o container é removido no fim.

Restaurar de verdade num ambiente: pare o stack, no Postgres do ambiente use
Backups → Restore com o arquivo escolhido, rode o deploy (o `migrate` leva o
banco à head) e confira como no passo 9 de "Ambiente do zero".
