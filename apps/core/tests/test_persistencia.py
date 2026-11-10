"""Persistência real do estado em Postgres.

Substitui o teste que usava `SqliteSaver`: com o checkpointer em Postgres, o que
precisa sobreviver é o estado no banco, não um arquivo local.
"""

from __future__ import annotations

from typing import Any

from conftest import Fakes, _servico_com_banco, resultado_jev
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.schemas import ChatRequest
from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage


def _servico(
    checkpointer: Any,
    fabrica: sessionmaker[Session],
    fakes: Fakes,
    settings: Settings,
) -> AgentService:
    return _servico_com_banco(settings, fakes, checkpointer, fabrica, MemoriaStorage())


def test_conversa_em_handoff_sobrevive_a_recriacao_do_servico(
    settings: Settings,
    checkpointer_pg: Any,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    fakes = Fakes()
    fakes.jev.resultado = resultado_jev("humano", 0.95)

    servico = _servico(checkpointer_pg, fabrica, fakes, settings)
    primeira = servico.process_message(
        ChatRequest(conversation_id=conversa, message="quero atendente")
    )
    assert primeira.status == "handoff"

    # Serviço novo, mesmo banco: o estado tem que vir do Postgres.
    fakes2 = Fakes()
    servico2 = _servico(checkpointer_pg, fabrica, fakes2, settings)
    segunda = servico2.process_message(ChatRequest(conversation_id=conversa, message="alguém aí?"))
    estado = servico2.graph.get_state(servico2.config(conversa)).values

    assert segunda.status == "with_human"
    assert segunda.answer == ""
    assert segunda.handoff_reason == "pediu_humano"
    assert estado["status"] == "handoff"
    assert fakes2.jev.chamadas == []
