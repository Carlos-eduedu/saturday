"""Testes da base do agente."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from conftest import Fakes, resposta_llm, resultado_jev

from saturday.agent.textos import MENSAGEM_BOAS_VINDAS, MENSAGEM_NAO_ENTENDI
from saturday.services.jev import JevClient, JevError
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings


def cid() -> str:
    return f"teste-{uuid.uuid4()}"


def test_1_pergunta_faq_answered(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev()
    fakes.llm.resposta = resposta_llm()

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Vocês atendem INSS?"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Sim, atendemos INSS."
    assert body["intent"] == "duvida"
    assert body["publico"] == "inss"


def test_2_pedido_humano_vai_para_handoff(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev("humano", 0.95)

    def nao_chamar(*args, **kwargs):
        pytest.fail("LLM não deveria ser chamado")

    fakes.llm.responder = nao_chamar  # type: ignore[method-assign]

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Quero falar com um atendente"},
    )

    body = r.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "pediu_humano"


def test_3_llm_sem_resposta_duas_vezes_vai_para_handoff(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev()
    fakes.llm.resposta = resposta_llm("", False)
    conversa = cid()

    def perguntar() -> dict:
        return client.post(
            "/chat", json={"conversation_id": conversa, "message": "Pergunta fora da FAQ"}
        ).json()

    primeira = perguntar()
    assert primeira["status"] == "answered"
    assert primeira["answer"] == MENSAGEM_NAO_ENTENDI

    segunda = perguntar()
    assert segunda["status"] == "handoff"
    assert segunda["handoff_reason"] == "sem_resposta"


def test_3b_resposta_da_faq_zera_a_contagem(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev()
    conversa = cid()

    def perguntar(resolvido: bool) -> dict:
        fakes.llm.resposta = resposta_llm("Da FAQ" if resolvido else "", resolvido)
        return client.post(
            "/chat", json={"conversation_id": conversa, "message": "Pergunta"}
        ).json()

    assert perguntar(False)["answer"] == MENSAGEM_NAO_ENTENDI
    assert perguntar(True)["answer"] == "Da FAQ"
    assert perguntar(False)["answer"] == MENSAGEM_NAO_ENTENDI


def test_3c_saudacao_sem_jornada_recebe_boas_vindas_sem_llm(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev("saudacao", publico="indefinido")

    r = client.post("/chat", json={"conversation_id": cid(), "message": "Oi"}).json()

    assert r["status"] == "answered"
    assert r["answer"] == MENSAGEM_BOAS_VINDAS
    assert r["intent"] == "saudacao"
    assert fakes.llm.chamadas_responder == []


def test_4_erro_do_jev_segue_para_llm(client, fakes: Fakes):
    fakes.jev.erro = JevError("indisponível")
    fakes.llm.resposta = resposta_llm("Resposta da FAQ")

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "Pergunta qualquer"},
    )

    body = r.json()
    assert body["status"] == "answered"
    assert body["answer"] == "Resposta da FAQ"
    assert body["intent"] is None


def test_5_apos_handoff_proxima_mensagem_nao_roda_grafo(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
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
    assert segunda.json()["status"] == "with_human"
    assert segunda.json()["answer"] == ""
    assert segunda.json()["handoff_reason"] == "pediu_humano"
    assert len(fakes.jev.chamadas) == 1


def test_6_webhook_recebe_payload(client, fakes: Fakes):
    fakes.webhook.configurado = True
    fakes.jev.resultado = resultado_jev()
    fakes.llm.resposta = resposta_llm("Resposta ao cliente")

    conversa = cid()
    r = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "Olá"},
    )

    assert r.status_code == 202
    assert r.json() == {"conversation_id": conversa, "status": "accepted"}
    assert len(fakes.webhook.enviados) == 1
    payload = fakes.webhook.enviados[0]
    assert payload["event"] == "agent.reply"
    assert payload["conversation_id"] == conversa
    assert payload["answer"] == "Resposta ao cliente"
    assert payload["status"] == "answered"
    assert "timestamp" in payload


def test_webhook_falha_nao_levanta():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fora do ar", request=request)

    settings = Settings(
        environment="pytest",
        webhook_url="https://webhook.test/agent",
        webhook_secret="segredo",  # noqa: S106  # segredo de teste
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = WebhookClient(http, settings)
        assert client.enviar({"conversation_id": "x", "status": "answered"}) is False


def test_jev_usa_decisions_api_e_pergunta_aceite():
    settings = Settings(
        environment="pytest",
        openrouter_api_key="chave",
        jev_model="typesafe/jev-1.13",
    )
    capturado: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["request"] = request
        capturado["corpo"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "duvida",
                        "confidence": 0.7,
                    },
                    "publico": {
                        "type": "choice",
                        "choice": "inss",
                        "confidence": 0.9,
                    },
                    "resposta_oferta": {
                        "type": "choice",
                        "choice": "aceita",
                        "confidence": 0.92,
                    },
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        resultado = JevClient(http, settings).classify("pode seguir", oferta_pendente=True)

    assert resultado.intent == "duvida"
    assert resultado.intent_confidence == 0.7
    assert resultado.publico == "inss"
    assert resultado.resposta_oferta == "aceita"
    assert resultado.resposta_oferta_confidence == 0.92
    request = capturado["request"]
    assert request.url.path.endswith("/api/alpha/decisions")
    assert request.headers["Authorization"] == "Bearer chave"
    assert capturado["corpo"]["state"]["ultima_mensagem"] == "pode seguir"
    assert capturado["corpo"]["questions"]["intent"]["type"] == "choice"
    assert capturado["corpo"]["questions"]["publico"]["type"] == "choice"
    assert capturado["corpo"]["questions"]["resposta_oferta"]["type"] == "choice"


def test_3d_saudacao_no_meio_da_jornada_segue_o_caminho_de_hoje(client, service, fakes: Fakes):
    conversa = cid()
    fakes.jev.resultado = resultado_jev()
    client.post("/chat", json={"conversation_id": conversa, "message": "Vocês atendem INSS?"})
    service.graph.update_state(service.config(conversa), {"oferta_pendente": True})
    fakes.jev.resultado = resultado_jev("saudacao", publico="indefinido")
    fakes.llm.resposta = resposta_llm("Resposta sobre a oferta")

    r = client.post("/chat", json={"conversation_id": conversa, "message": "oi"}).json()

    assert r["answer"] == "Resposta sobre a oferta"
    assert r["intent"] != "saudacao"


def test_3e_publico_sem_clareza_nao_troca_o_publico_conhecido(client, fakes: Fakes):
    conversa = cid()
    fakes.jev.resultado = resultado_jev(publico="clt")
    client.post("/chat", json={"conversation_id": conversa, "message": "sou CLT"})

    # Público citado sem clareza (o Jev real põe a negação em `indefinido`).
    fakes.jev.resultado = resultado_jev(
        publico="servidor_publico",
        probabilities={"intent": {"duvida": 0.9}, "publico": {"servidor_publico": 0.4}},
    )
    r = client.post(
        "/chat", json={"conversation_id": conversa, "message": "Eu não sou servidor público"}
    ).json()

    assert r["publico"] == "clt"
