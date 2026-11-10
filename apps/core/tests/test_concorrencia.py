"""Trava por conversa: turnos inteiros, sem perda de histórico."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from saturday.schemas import ChatRequest


def test_duas_threads_no_mesmo_conversation_id(service, fakes):
    conversa = "concorrente"

    def enviar() -> None:
        service.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: enviar(), range(2)))

    estado = service.graph.get_state(service.config(conversa)).values
    assert len(estado["messages"]) == 4
    assert fakes.llm.chamadas_responder
