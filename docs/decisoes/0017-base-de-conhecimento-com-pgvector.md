# 0017 — Base de conhecimento (RAG) com pgvector e embeddings da OpenRouter

- **Data:** 2026-11-14
- **Status:** aceita

## Contexto

O nó de respostas ancora o LLM na FAQ fixa de `faq.py`, que vai inteira no
prompt. O gestor pediu, na aba Agente, uma base de conhecimento com fontes
adicionadas, atualizadas e removidas pelo painel, status de indexação e data de
atualização. Escolheu busca semântica (RAG), pgvector no Postgres e fontes em
texto digitado, PDF e Markdown/TXT.

## Decisão

- Imagem do Postgres `pgvector/pgvector:pg17` (mesmo Postgres 17, com a extensão
  `vector`) no compose, no guia de deploy e no teste de restauração. A migração
  `c5a9e3f7b1d4` cria a extensão; sem ela, o `migrate` falha e a API e o worker
  não sobem.
- Tabelas `fontes_conhecimento` e `trechos_conhecimento`. A coluna `vector` não
  tem dimensão fixa: cada trecho guarda o modelo que o gerou e a busca só compara
  trechos do modelo vigente. Busca exata (sem índice HNSW), suficiente para
  centenas de trechos; índice entra quando a base crescer.
- O arquivo vai para o storage privado; o texto é extraído no worker (`pypdf`
  para PDF, que é dependência nova), quebrado em trechos de até 1.200 caracteres
  com sobreposição, e cada trecho recebe embedding pela OpenRouter
  (`POST /api/v1/embeddings`, parceiro que já existe). O modelo é o papel
  `embeddings` da configuração versionada (decisão 0016), padrão
  `openai/text-embedding-3-small`; trocar manda todas as fontes para a fila.
- Na resposta, a pergunta busca até 4 trechos com similaridade ≥ 0,35, que entram
  no prompt ao lado da FAQ fixa e "valem como a FAQ". Sem trecho relevante, ou com
  a busca fora do ar, o prompt é o de antes. A regra 2 continua: o LLM só usa o
  que está escrito; sem resposta, handoff.
- Editar exige a permissão "editar o agente"; cada ação grava `auditoria`.

## Consequências

- Trocar a imagem de um banco que já roda em `postgres:17-alpine` muda a
  biblioteca de ordenação de texto (musl → glibc): depois da troca, rode
  `REINDEX DATABASE saturday`. Faça backup antes.
- Uma fonte editada sai da busca até terminar a reindexação (segundos).
- Conteúdo das fontes é informação pública da MEX; não suba dado pessoal nelas.
