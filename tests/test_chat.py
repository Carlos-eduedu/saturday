"""Testes da base do agente (etapa 2)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from saturday.api import app
from saturday.services import jev as jev_service
from saturday.services import llm as llm_service
from saturday.services import openrouter as openrouter_service
from saturday.services import webhook as webhook_service
from saturday.settings import get_settings

client = TestClient(app)


def cid() -> str:
    return f"teste-{uuid.uuid4()}"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    monkeypatch.setenv("SATURDAY_WEBHOOK_URL", "")
    monkeypatch.setenv("SATURDAY_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SATURDAY_LLM_MODEL", "")
    monkeypatch.setenv("SATURDAY_VISION_MODEL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def classificar(intent="duvida", conf=0.9, publico="inss"):
    return jev_service.JevResult(
        intent=intent,
        intent_confidence=conf,
        publico=publico,
        publico_confidence=0.9,
    )


def responder(resposta="Sim, atendemos INSS.", resolvido=True):
    return llm_service.LLMAnswer(resposta=resposta, resolvido=resolvido)


def test_1_pergunta_faq_answered(monkeypatch):
    monkeypatch.setattr(jev_service, "classify", lambda *a, **k: classificar())
    monkeypatch.setattr(llm_service, "responder", lambda *a, **k: responder())

    r = client.post("/chat", json={"conversation_id": cid(), "message": "Vocês atendem INSS?"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Sim, atendemos INSS."
    assert body["intent"] == "duvida"
    assert body["publico"] == "inss"


def test_2_pedido_humano_vai_para_handoff(monkeypatch):
    monkeypatch.setattr(jev_service, "classify", lambda *a, **k: classificar("humano", 0.95))
    monkeypatch.setattr(
        llm_service,
        "responder",
        lambda *a, **k: pytest.fail("LLM não deveria ser chamado"),
    )

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Quero falar com um atendente"},
    )

    body = r.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "pediu_humano"


def test_3_llm_sem_resposta_vai_para_handoff(monkeypatch):
    monkeypatch.setattr(jev_service, "classify", lambda *a, **k: classificar())
    monkeypatch.setattr(llm_service, "responder", lambda *a, **k: responder("", False))

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Pergunta fora da FAQ"},
    )

    body = r.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "sem_resposta"


def test_4_erro_do_jev_segue_para_llm(monkeypatch):
    def falhar(*args, **kwargs):
        raise jev_service.JevError("indisponível")

    monkeypatch.setattr(jev_service, "classify", falhar)
    monkeypatch.setattr(llm_service, "responder", lambda *a, **k: responder("Resposta da FAQ"))

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Pergunta qualquer"},
    )

    body = r.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Resposta da FAQ"
    assert body["intent"] is None


def test_5_apos_handoff_proxima_mensagem_nao_roda_grafo(monkeypatch):
    chamadas = {"jev": 0}

    def classificar_humano(*args, **kwargs):
        chamadas["jev"] += 1
        return classificar("humano", 0.95)

    monkeypatch.setattr(jev_service, "classify", classificar_humano)
    conversa = cid()

    primeira = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "Quero um atendente"},
    )
    assert primeira.json()["status"] == "handoff"

    segunda = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "Alguém aí?"},
    )

    assert segunda.status_code == 200
    assert segunda.json()["status"] == "handoff"
    assert chamadas["jev"] == 1


def test_6_webhook_recebe_payload(monkeypatch):
    monkeypatch.setenv("SATURDAY_WEBHOOK_URL", "https://webhook.test/agent")
    get_settings.cache_clear()
    enviados = []

    class Resposta:
        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        enviados.append((url, json, timeout))
        return Resposta()

    monkeypatch.setattr(webhook_service.httpx, "post", fake_post)
    monkeypatch.setattr(jev_service, "classify", lambda *a, **k: classificar())
    monkeypatch.setattr(llm_service, "responder", lambda *a, **k: responder("Resposta ao cliente"))

    conversa = cid()
    r = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "Olá"},
    )

    assert r.status_code == 202
    assert r.json() == {"conversation_id": conversa, "status": "accepted"}
    assert len(enviados) == 1
    url, payload, timeout = enviados[0]
    assert url == "https://webhook.test/agent"
    assert timeout == 10
    assert payload["event"] == "agent.reply"
    assert payload["conversation_id"] == conversa
    assert payload["answer"] == "Resposta ao cliente"
    assert payload["status"] == "answered"
    assert "timestamp" in payload


def test_webhook_falha_nao_levanta(monkeypatch):
    monkeypatch.setenv("SATURDAY_WEBHOOK_URL", "https://webhook.test/agent")
    get_settings.cache_clear()

    def fake_post(*args, **kwargs):
        raise webhook_service.httpx.ConnectError("fora do ar")

    monkeypatch.setattr(webhook_service.httpx, "post", fake_post)

    assert webhook_service.send({"conversation_id": "x", "status": "answered"}) is False


def test_jev_usa_decisions_api_e_pergunta_aceite(monkeypatch):
    monkeypatch.setenv("SATURDAY_OPENROUTER_API_KEY", "chave")
    monkeypatch.setenv("SATURDAY_JEV_MODEL", "typesafe/jev-1.13")
    get_settings.cache_clear()
    chamadas = []

    def fake_post(url, api_key, payload, timeout):
        chamadas.append((url, api_key, payload, timeout))
        return {
            "answers": {
                "intent": {"type": "choice", "choice": "duvida", "confidence": 0.7},
                "publico": {"type": "choice", "choice": "inss", "confidence": 0.9},
                "resposta_oferta": {
                    "type": "choice",
                    "choice": "aceita",
                    "confidence": 0.92,
                },
            }
        }

    monkeypatch.setattr(openrouter_service, "post_json", fake_post)

    resultado = jev_service.classify("pode seguir", oferta_pendente=True)

    assert resultado.intent == "duvida"
    assert resultado.intent_confidence == 0.7
    assert resultado.publico == "inss"
    assert resultado.resposta_oferta == "aceita"
    assert resultado.resposta_oferta_confidence == 0.92
    assert len(chamadas) == 1
    url, api_key, payload, timeout = chamadas[0]
    assert url.endswith("/api/alpha/decisions")
    assert api_key == "chave"
    assert timeout == 5
    assert payload["state"]["ultima_mensagem"] == "pode seguir"
    assert payload["questions"]["intent"]["type"] == "choice"
    assert payload["questions"]["publico"]["type"] == "choice"
    assert payload["questions"]["resposta_oferta"]["type"] == "choice"
