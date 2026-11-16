"""Liberação manual e automática do handoff."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import resultado_jev

from saturday.schemas import ChatRequest

TZ = ZoneInfo("America/Sao_Paulo")


def test_release_devolve_conversa_ao_agente(client, fakes):
    conversa = "release-manual"
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    assert (
        client.post(
            "/chat",
            json={"conversation_id": conversa, "message": "quero atendente"},
        ).json()["status"]
        == "handoff"
    )

    fakes.jev.resultado = resultado_jev()
    liberacao = client.post(f"/conversations/{conversa}/release")
    assert liberacao.status_code == 200
    assert liberacao.json() == {"conversation_id": conversa, "status": "in_progress"}

    resposta = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "agora sim"},
    ).json()
    assert resposta["status"] == "answered"
    assert resposta["handoff_reason"] is None
    assert len(fakes.jev.chamadas) == 2


def test_release_inexistente_retorna_404(client):
    assert client.post("/conversations/nao-existe/release").status_code == 404


def test_liberacao_automatica_apos_prazo(service, fakes, monkeypatch):
    service.settings.handoff_auto_release_horas = 1
    conversa = "release-auto"
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    pedido = ChatRequest(conversation_id=conversa, message="quero atendente")
    assert service.process_message(pedido).status == "handoff"

    # O prazo conta de `conversas.atendimento_em`, gravado pelo banco agora.
    duas_horas_depois = datetime.now(TZ) + timedelta(hours=2)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: duas_horas_depois)
    fakes.jev.resultado = resultado_jev()

    resposta = service.process_message(ChatRequest(conversation_id=conversa, message="oi de novo"))

    assert resposta.status == "answered"
    assert resposta.handoff_reason is None
    assert len(fakes.jev.chamadas) == 2
    estado = service.graph.get_state(service.config(conversa)).values
    assert estado["status"] == "answered"
    assert estado["handoff_em"] is None
