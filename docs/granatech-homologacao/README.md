# Homologação com a Granatech

Material recebido da Granatech para a homologação da API, sem segredos nem dados
pessoais: a chave da api-dev, os tokens, os telefones, os e-mails, os nomes e os
CPFs dos exemplos foram removidos ou trocados pelos dados de teste. Um teste
(`apps/core/tests/test_documentos_sem_segredos.py`) falha se algum voltar.

| Arquivo | O que é |
| --- | --- |
| `roteiro-homologacao.md` | Roteiro da Granatech: ambientes, fases da homologação e mensagens de cada etapa |
| `chat.md` | Conversa com a Granatech no WhatsApp (pessoas trocadas pelo papel: `[MEX]`, `[Granatech]`) |
| `webhook-consultas.md` | Formato do webhook de consultas (os PDFs originais ficam fora do git, como todo `*.pdf`) |
| `webhook-propostas.md` | Status e notificações de propostas |
| `postman-consultas.json`, `postman-contratacao.json` | Collections do Postman (preencha `api_key` localmente) |

As evidências das fases saem de `scripts/homologacao_granatech.py` (ver
[`../granatech.md`](../granatech.md)).
