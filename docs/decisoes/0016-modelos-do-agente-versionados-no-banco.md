# 0016 — Modelos de IA por etapa versionados no banco, editáveis pelo painel

- **Data:** 2026-11-14
- **Status:** aceita

## Contexto

O `AGENTS.md` mantém `LLM_MODEL`, `VISION_MODEL`, `JEV_MODEL` e
`TRANSCRICAO_MODELO` como variáveis de ambiente "como hoje": trocar um modelo
exige mudar a variável no Dokploy e fazer redeploy. O gestor pediu a aba
**Agente** no painel para ver e trocar o modelo de cada etapa, comparar opções,
testar antes de salvar, manter histórico de versões e controlar quem edita.

## Decisão

- Tabela `config_agente`, só de acréscimo: cada salvar ou restaurar cria uma
  versão nova (número, modelos por papel, nota, autor, data, `restaurada_de`).
  A de maior número é a vigente.
- `agente_config.Modelos` resolve o modelo de cada papel (`jev`, `llm`,
  `visao`, `transcricao`) a cada chamada: versão vigente, e a variável de
  ambiente quando o papel está vazio, quando não há versão ou quando o banco
  falha. Cache de 5 s; a troca vale a partir do próximo turno, sem redeploy.
- Salvar exige a permissão nova `usuarios_painel.pode_editar_agente`,
  independente do perfil (a migração liga para os gestores ativos). Salvar
  confere a versão que a pessoa estava vendo (409 se outra pessoa salvou antes)
  e valida contra o catálogo: o modelo existe, aceita imagem na etapa de visão e
  aceita resposta em JSON. Antes de salvar, o painel mostra quantas travas de
  conversa estão seguras (turnos em andamento): eles terminam com a
  configuração anterior.
- Catálogo, preço e limites vêm de `GET https://openrouter.ai/api/v1/models`
  (público, sem chave), guardados em `catalogo_modelos` com a data da leitura;
  o painel mostra sempre a fonte e essa data. Latência não é publicada pela
  OpenRouter: é a medida nas nossas chamadas dos últimos 7 dias (cada chamada
  passa a registrar o `modelo` na trilha do turno).
- Jev (OpenRouter Decisions) e transcrição (provedor compatível com a OpenAI)
  ficam fora do catálogo: id digitado, sem preço na tela.
- "Testar" faz uma chamada real e paga, só para gestor, com o mesmo prompt do
  atendimento (classificação e FAQ). A auditoria guarda etapa, modelo e erro,
  nunca o texto digitado nem a resposta.

## Consequências

- As variáveis de ambiente continuam valendo como padrão e saída de emergência;
  o `.env.example` não muda.
- A regra 2 não muda: o modelo trocado continua só classificando e respondendo
  ancorado na FAQ; os prompts e as regras de decisão seguem em código.
