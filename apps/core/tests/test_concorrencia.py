"""Trava por conversa: turnos inteiros, sem perda de histórico.

Exige Postgres porque é onde vive a serialização (`pg_advisory_xact_lock`).
Com o `threading.Lock` antigo, dois processos nunca se enxergavam.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import Fakes

from saturday.agent.service import AgentService
from saturday.schemas import ChatRequest


def test_duas_threads_no_mesmo_conversation_id(
    service_pg: AgentService,
    fakes: Fakes,
    conversa: str,
) -> None:

    def enviar(_: int) -> None:
        service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(enviar, range(2)))

    estado = service_pg.graph.get_state(service_pg.config(conversa)).values

    # Dois turnos completos: nenhum sobrescreveu o outro.
    assert len(estado["messages"]) == 4
    assert fakes.llm.chamadas_responder
