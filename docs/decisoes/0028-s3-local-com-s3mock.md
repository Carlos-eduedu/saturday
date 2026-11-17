# 0028 — S3 local do compose com adobe/s3mock no lugar do MinIO

- **Data:** 2026-11-17
- **Status:** aceita
- **Desvia de:** especificação, "Variáveis de ambiente e compose" (serviço e
  profile `minio`, "endpoint vazio = MinIO interno")

## Contexto

A imagem `minio/minio:latest` saiu do Docker Hub: o profile `minio` falhava no
pull em máquina sem a imagem em cache (issue #12). O `infra/painel_local.sh`
já usava o `adobe/s3mock` por esse motivo.

## Decisão

- O compose tem um S3 local só: serviço e profile `s3`, imagem
  `adobe/s3mock:5.2.3` (tag fixa), a mesma do `infra/painel_local.sh`. O
  `minio-init` saiu: o bucket nasce por
  `COM_ADOBE_TESTING_S3MOCK_STORE_INITIAL_BUCKETS`.
- Os arquivos ficam no volume `s3_dados` (`STORE_ROOT` e
  `STORE_RETAIN_FILES_ON_EXIT`). O container roda como root porque a imagem usa
  o uid 1000, que não escreve em volume nomeado.
- O override local publica o serviço na porta `9000` do host; a `9090` fica com
  o S3 do `painel_local.sh`.
- "Endpoint vazio = MinIO interno" nunca foi verdade no código: com
  `SATURDAY_S3_ENDPOINT` vazio o cliente fala com a AWS. Com o profile `s3`, o
  `.env` leva `SATURDAY_S3_ENDPOINT=http://s3:9090` e qualquer valor na chave e
  no segredo.

## Consequências

- Quem tem `COMPOSE_PROFILES=postgres,minio` no `.env` troca por `postgres,s3`.
  O volume antigo `minio_dados` fica órfão e pode ser apagado; os anexos que
  estavam nele não são migrados.
- O s3mock é só para desenvolvimento: aceita qualquer credencial. `dev`,
  `homolog` e `prod` no Dokploy seguem com `COMPOSE_PROFILES` vazio e bucket
  externo; nada muda lá.
- O caminho real do `S3Storage` tem teste de integração
  (`apps/core/tests/test_storage_s3_real.py`), pulado sem
  `SATURDAY_TEST_S3_ENDPOINT`: o CI não o roda, é conferência à mão.

## Alternativas descartadas

- **Outra origem da imagem do MinIO** (`cgr.dev/chainguard/minio`): baixa, mas
  não tem shell, não foi testada com o `minio-init` e deixaria o projeto com
  dois S3 locais.
