# 0014 — Evidências da homologação Granatech geradas pelo painel, sem script

- **Data:** 2026-11-13
- **Status:** aceita

## Contexto

A Fase 7 do `AGENTS.md` pede o script `scripts/homologacao_granatech.py`, que
gera as evidências das duas fases da homologação contra a api-dev. Para rodá-lo
é preciso ter a chave da Granatech e a `SATURDAY_API_KEY` na máquina local, e o
script lê os webhooks pela rota `GET /eventos/granatech/{id}`, que existe só
para ele. O gestor quer gerar as evidências pelo painel, sem terminal e sem
segredo fora do servidor.

Os webhooks das consultas e propostas de homologação hoje viram alertas de
"consulta desconhecida" e "proposta desconhecida", porque elas não pertencem a
nenhuma conversa.

## Decisão

- Uma seção **Homologação** no fim da aba Granatech, só para o gestor, só com
  `SATURDAY_ENVIRONMENT` em `dev` ou `homolog` e com a base da Granatech fora de
  `api.granatech.com.br`. Fora disso a seção some e a API responde 404.
- Um botão por fase. Cada clique cria uma **rodada** (tabela
  `homologacoes_granatech`, com os passos em JSONB e os segredos trocados por
  `[removido]`), com confirmação e auditoria. Uma rodada por vez; sem cancelar.
- O worker pega a rodada pendente com `FOR UPDATE SKIP LOCKED` e a executa numa
  thread própria, para não travar o outbox; os webhooks são lidos direto de
  `eventos_recebidos`. Se o worker reiniciar no meio, a rodada fica
  `interrompida`.
- As consultas e propostas da homologação não entram em `consultas_granatech`,
  `propostas_granatech` nem na cota. O worker reconhece os ids das rodadas e
  só registra o webhook, sem alerta.
- O painel mostra cada evidência (para print) e baixa um `.zip` com os JSON e o
  `RELATORIO.md`, montado na hora.
- Saem o script, a rota `GET /eventos/granatech/{id}` e o teste do script.

## Consequências

- O painel passa a ser o único caminho para gerar evidências; com o worker
  parado, não há homologação.
- Os webhooks só chegam ao deploy cadastrado na Granatech: no dev, o item "via
  webhook" falha enquanto a Granatech apontar para o homolog. A seção mostra a
  URL esperada para deixar isso claro.
- Uma rodada interrompida não é retomada; o gestor gera outra.
