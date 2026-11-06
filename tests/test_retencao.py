"""Retenção do extrato e exclusão (LGPD)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from saturday.schemas import ChatRequest

TZ = ZoneInfo("America/Sao_Paulo")


def test_extrato_com_31_dias_e_limpo_antes_do_turno(service, fakes, monkeypatch):
    agora_fixo = datetime(2026, 10, 8, 12, 0, tzinfo=TZ)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: agora_fixo)
    conversa = "retencao-31"
    service.graph.update_state(
        service.config(conversa),
        {
            "hiscon": {"ehHiscon": True},
            "portability_result": {"ok": True, "contratos": []},
            "oferta_pendente": True,
            "hiscon_recebido_em": (agora_fixo - timedelta(days=31)).isoformat(),
        },
    )

    service.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    estado = service.graph.get_state(service.config(conversa)).values

    assert estado["hiscon"] is None
    assert estado["portability_result"] is None
    assert estado["oferta_pendente"] is False
    assert estado["hiscon_recebido_em"] is None
    assert len(fakes.jev.chamadas) == 1


def test_delete_apaga_conversa_e_get_seguinte_retorna_404(client):
    conversa = "apagar-lgpd"
    assert (
        client.post("/chat", json={"conversation_id": conversa, "message": "oi"}).status_code == 200
    )
    assert client.get(f"/conversations/{conversa}").status_code == 200

    assert client.delete(f"/conversations/{conversa}").status_code == 204
    assert client.get(f"/conversations/{conversa}").status_code == 404


def test_get_nao_expoe_mensagens_extrato_nem_cliente(client):
    conversa = "sem-dados"
    client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "segredo do cliente",
            "cliente": {"uf": "MS"},
        },
    )

    body = client.get(f"/conversations/{conversa}").json()

    assert body["conversation_id"] == conversa
    assert "messages" not in body
    assert "hiscon" not in body
    assert "cliente" not in body
    assert "segredo do cliente" not in str(body)
