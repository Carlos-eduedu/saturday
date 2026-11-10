"""Idempotência por message_id."""

from __future__ import annotations

from conftest import Fakes
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Outbox


def test_mesmo_message_id_nao_roda_o_grafo_duas_vezes(client: TestClient, fakes: Fakes) -> None:
    conversa = "idempotente"
    payload = {"conversation_id": conversa, "message": "oi", "message_id": "msg-1"}

    primeira = client.post("/chat", json=payload)
    segunda = client.post("/chat", json=payload)

    assert primeira.status_code == 200
    assert primeira.json()["status"] == "answered"
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "duplicate"
    # O repetido devolve a MESMA resposta já dada, não uma vazia.
    assert segunda.json()["answer"] == primeira.json()["answer"]
    assert segunda.json()["answer"] != ""
    assert len(fakes.jev.chamadas) == 1


def test_duplicado_nao_enfileira_envio_nem_roda_de_novo(
    client_pg: TestClient,
    fakes: Fakes,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    fakes.webhook.configurado = True
    payload = {"conversation_id": conversa, "message": "oi", "message_id": "msg-2"}

    assert client_pg.post("/chat", json=payload).status_code == 202
    assert client_pg.post("/chat", json=payload).status_code == 202

    with fabrica() as sessao:
        pendentes = sessao.scalar(select(func.count()).select_from(Outbox))

    # Um turno, um envio: o duplicado não enfileira nada nem roda o grafo.
    assert pendentes == 1
    assert len(fakes.jev.chamadas) == 1
