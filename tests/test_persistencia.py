"""Persistência real com SqliteSaver."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from conftest import Fakes, resultado_jev
from langgraph.checkpoint.sqlite import SqliteSaver

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.schemas import ChatRequest
from saturday.settings import Settings


def _servico(
    caminho: Path,
    fakes: Fakes,
    settings: Settings,
) -> tuple[AgentService, sqlite3.Connection]:
    conexao = sqlite3.connect(str(caminho), check_same_thread=False)
    checkpointer = SqliteSaver(conexao)
    checkpointer.setup()
    grafo = build_graph(checkpointer)
    contexto = AgentContext(
        jev=fakes.jev,
        llm=fakes.llm,
        anexos=fakes.anexos,
    )
    servico = AgentService(
        graph=grafo,
        context=contexto,
        webhook=fakes.webhook,
        settings=settings,
        checkpointer=checkpointer,
    )
    return servico, conexao


def test_conversa_em_handoff_sobrevive_a_recriacao_do_servico(tmp_path):
    settings = Settings(environment="pytest", checkpoint_path=tmp_path / "checkpoints.sqlite")
    fakes = Fakes()
    fakes.jev.resultado = resultado_jev("humano", 0.95)

    servico, conexao = _servico(settings.checkpoint_path, fakes, settings)
    primeira = servico.process_message(
        ChatRequest(conversation_id="persistente", message="quero atendente")
    )
    assert primeira.status == "handoff"
    conexao.close()

    fakes2 = Fakes()
    servico2, conexao2 = _servico(settings.checkpoint_path, fakes2, settings)
    segunda = servico2.process_message(
        ChatRequest(conversation_id="persistente", message="alguém aí?")
    )
    estado = servico2.graph.get_state(servico2.config("persistente")).values
    conexao2.close()

    assert segunda.status == "with_human"
    assert segunda.answer == ""
    assert segunda.handoff_reason == "pediu_humano"
    assert estado["status"] == "handoff"
    assert fakes2.jev.chamadas == []
