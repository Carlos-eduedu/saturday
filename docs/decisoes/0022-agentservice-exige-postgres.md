# 0022 — O `AgentService` exige o Postgres, também nos testes

- **Data:** 2026-11-16
- **Status:** aceita
- **Altera:** uma consequência da 0003

## Contexto

Em dev, homolog e prod o serviço nunca subiu sem banco. Só o ambiente `pytest`
montava o `AgentService` sem fábrica de sessões, e para isso o serviço carregava
um segundo caminho: onze desvios "tem banco?", o handoff decidido pelo
checkpoint (`_silencio_pelo_checkpoint`), a entrega direta pelo webhook e um
`RegistroMemoria` que não gravava nada.

Cerca de 50 testes do agente rodavam nesse caminho. Passavam sem provar
`mensagens`, `outbox` nem o estado de atendimento, e o handoff pelo checkpoint
é justamente o que a decisão 0003 trocou pela tabela `conversas`.

## Decisão

- A fábrica de sessões é obrigatória no `AgentService`. O caminho sem banco sai
  do serviço e do fechamento do turno.
- `RegistroDoTurno` deixa de ser uma costura: sobra o `RegistroPostgres`.
- Os fixtures `service`, `app` e `client` usam o Postgres de teste, com o
  checkpoint em memória. Sem `SATURDAY_TEST_DATABASE_URL` esses testes são
  pulados, como os de banco já eram.
- O `lifespan` cria o engine em todo ambiente. Em `pytest` continuam em memória
  só o checkpointer e o storage, que têm dois adaptadores de verdade.
- Turno de sistema para uma conversa que não está em `conversas` não roda: vira
  aviso no log. Os jobs sempre partem de uma linha da tabela.

## Alternativas descartadas

- **Manter a memória atrás de uma costura**, com um guardador do estado de
  atendimento e dois adaptadores. O adaptador de memória seria uma segunda
  implementação das regras de handoff, assumida e liberação: o mesmo defeito
  em outro lugar.

## Consequências

- `uv run pytest -q` sem a variável do banco deixa de cobrir o agente: pula
  385 testes e roda 348. Quem mexe em `agent/` roda com o Postgres de teste.
- A consequência da 0003 "conversas do `POST /chat` sem Postgres não têm onde
  guardar o estado" deixa de existir.
- **Ficou de fora:** o "sem banco" dos clientes do contexto (`agent/clt`,
  `fontes/brasilapi.py`, `conhecimento.py`, `agente_config.py`,
  `web/composicao.py`) e dos webhooks em `web/api/`. O `AgentContext.fabrica`
  continua opcional.
