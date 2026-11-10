"""Idempotência por message_id."""

from __future__ import annotations


def test_mesmo_message_id_nao_roda_o_grafo_duas_vezes(client, fakes):
    conversa = "idempotente"
    payload = {"conversation_id": conversa, "message": "oi", "message_id": "msg-1"}

    primeira = client.post("/chat", json=payload)
    segunda = client.post("/chat", json=payload)

    assert primeira.status_code == 200
    assert primeira.json()["status"] == "answered"
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "duplicate"
    assert segunda.json()["answer"] == ""
    assert len(fakes.jev.chamadas) == 1


def test_duplicado_no_webhook_nao_envia_nada(client, fakes):
    fakes.webhook.configurado = True
    conversa = "idempotente-webhook"
    payload = {"conversation_id": conversa, "message": "oi", "message_id": "msg-2"}

    assert client.post("/chat", json=payload).status_code == 202
    assert len(fakes.webhook.enviados) == 1

    assert client.post("/chat", json=payload).status_code == 202
    assert len(fakes.webhook.enviados) == 1
