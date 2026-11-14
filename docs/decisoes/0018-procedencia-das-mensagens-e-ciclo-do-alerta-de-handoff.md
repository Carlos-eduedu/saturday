# 0018 — Procedência das mensagens da IA e ciclo do alerta de handoff

- **Data:** 2026-11-14
- **Status:** aceita

## Contexto

O critique do painel deixou dois achados que só o backend resolve.

**Procedência.** Para conferir de onde veio cada valor que a IA mandou ao
cliente, o painel casa a fala com o turno pelo horário. `mensagens` não guarda
o turno nem qual mensagem fixa foi usada, então o casamento erra quando dois
turnos ficam próximos e não diz se o texto é fixo ou escrito pelo modelo.

**Alerta de handoff.** O alerta `handoff` (ou `erro_interno`) é o que diz à
equipe por que a conversa saiu da IA. Hoje ele tem dois furos:

- dois caminhos põem a conversa em `handoff` sem abrir alerta: a migração do
  handoff antigo, gravado só no checkpoint, e o desfazer de um assumir;
- assumir ou devolver a conversa não resolve o alerta, que fica aberto até
  alguém clicar em "resolver" na aba Alertas, mesmo com o caso já tratado.

## Decisão

**Procedência das mensagens**

- Cada mensagem de saída da IA guarda `turno_id` (o turno que a produziu) e
  `chave_mensagem`.
- `chave_mensagem` é a chave da mensagem fixa usada (`oferta`,
  `textos:boas_vindas`, `handoff:{motivo}`). Quando a fala junta mais de uma
  mensagem fixa, a chave é composta com `+`, na ordem do texto
  (`consultando+termo_link`, `aviso_teto+oferta`).
- `chave_mensagem` nula significa **"o modelo escreveu"** (resposta da FAQ).
  Linhas anteriores a esta decisão também ficam nulas e sem `turno_id`: o
  painel cai no casamento pelo horário só para elas. Sem backfill.

**Ciclo do alerta de handoff**

- Toda entrada em `handoff` abre o alerta, inclusive a migração do handoff do
  checkpoint. Não abre um segundo alerta do mesmo tipo se já houver um aberto
  na mesma conversa.
- O alerta se resolve sozinho, em nome de quem agiu, com aviso pelo SSE:
  - **assumir** resolve `handoff` e `erro_interno`;
  - **devolver** resolve esses dois e também `sem_resposta`;
  - **transferir** não resolve nada: a conversa continua com humano;
  - `evento_com_humano` nunca se resolve sozinho, porque traz um fato do banco
    que alguém precisa ler.
- Os ids resolvidos vão no `detalhe` da auditoria da ação.
- **Desfazer** reabre os alertas que a ação desfeita resolveu (pelos ids da
  auditoria). Numa auditoria antiga, sem ids, se a conversa volta para
  `handoff`, abre um alerta `handoff` (sem duplicar). A auditoria do desfazer
  guarda `alertas_reabertos`.
- O alerta aberto na migração do handoff antigo reinicia o relógio da
  liberação automática, como já acontecia ao mudar o atendimento.

## Alternativas descartadas

- **Guardar a procedência só no turno.** O turno não sabe qual das falas é a
  dele quando há mais de uma saída próxima, e não distingue texto fixo de
  texto do modelo.
- **Resolver o alerta em qualquer mudança de atendimento.** Transferir não
  trata o caso, só troca quem cuida dele; resolver ali apagaria o motivo da
  lista de quem recebe a conversa.
- **Apagar o alerta em vez de resolver.** Perde o rastro de quem tratou e
  quando, e o desfazer não teria o que reabrir.

## Consequências

- `mensagens` ganha duas colunas e uma migração; o INSS segue igual, porque o
  campo no estado é opcional.
- A aba Alertas deixa de acumular handoffs já tratados, e o desfazer devolve a
  conversa ao estado exato de antes, alerta incluído.
