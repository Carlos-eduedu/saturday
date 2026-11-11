# Deploy no Dokploy

O Saturday roda no Dokploy da Dynatech (`infra.dynatech.systems`), projeto
`Saturday`, com um ambiente por estágio. Cada ambiente tem o seu stack compose,
o seu Postgres gerenciado pelo Dokploy e o seu bucket S3 externo. Alterar
qualquer coisa no painel segue a regra de `decisoes/0005`.

> Este guia começa a Fase 7. Backup com teste de restauração e o passo a passo
> de um ambiente do zero entram quando a fase for fechada.

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
