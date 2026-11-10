"""Testes das correções de comportamento (etapa 3)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import (
    Fakes,
    anexo_fake,
    extrato_fake,
    resposta_llm,
    resultado_jev,
)
from langchain_core.messages import AIMessage

from saturday.services.jev import JevClient, JevResult, _choice
from saturday.services.llm import LLMClient, LLMError
from saturday.settings import Settings


def cid() -> str:
    return f"comportamento-{uuid.uuid4()}"


def _pergunta_data(client, fakes: Fakes) -> str:
    fakes.llm.extrato = extrato_fake()
    conversa = cid()
    resposta = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "segue o extrato",
            "attachments": [anexo_fake()],
        },
    )
    assert "data de nascimento" in resposta.json()["answer"].lower()
    return conversa


def test_handoff_nao_repete_mensagem(client, fakes: Fakes):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    conversa = cid()

    assert (
        client.post(
            "/chat",
            json={"conversation_id": conversa, "message": "quero atendente"},
        ).json()["status"]
        == "handoff"
    )

    body = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "alguém?"},
    ).json()
    assert body["status"] == "with_human"
    assert body["answer"] == ""
    assert body["handoff_reason"] == "pediu_humano"


class GrafoQuebrado:
    def __init__(self) -> None:
        self.estado: dict[str, Any] = {}
        self.atualizacao: dict[str, Any] | None = None

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(values=self.estado)

    def invoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("falha proposital")

    def update_state(self, config: dict[str, Any], valores: dict[str, Any]) -> None:
        self.estado.update(valores)
        self.atualizacao = valores


def test_erro_inesperado_vira_handoff_erro_interno(client, service, fakes: Fakes):
    service.graph = GrafoQuebrado()

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "oi"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "erro_interno"
    assert "problema para continuar" in body["answer"].lower()


def test_erro_inesperado_no_webhook_envia_evento(client, service, fakes: Fakes):
    fakes.webhook.configurado = True
    service.graph = GrafoQuebrado()

    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "oi"},
    )

    assert r.status_code == 202
    assert len(fakes.webhook.enviados) == 1
    payload = fakes.webhook.enviados[0]
    assert payload["status"] == "handoff"
    assert payload["handoff_reason"] == "erro_interno"
    assert "problema para continuar" in payload["answer"].lower()


def test_pedido_humano_durante_coleta_vai_para_handoff(client, fakes: Fakes):
    conversa = _pergunta_data(client, fakes)
    fakes.jev.resultado = resultado_jev("humano", 0.95)

    body = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "quero falar com um atendente",
        },
    ).json()

    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "pediu_humano"


def test_texto_invalido_durante_coleta_pergunta_de_novo_e_conta(client, fakes: Fakes, service):
    conversa = _pergunta_data(client, fakes)
    fakes.jev.resultado = resultado_jev("duvida")

    body = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "não sei"},
    ).json()

    assert body["status"] == "answered"
    assert "não consegui entender a data" in body["answer"].lower()
    estado = service.graph.get_state(service.config(conversa)).values
    assert estado["tentativas_coleta"] == 1
    assert estado["aguardando"] == "data_nascimento"


def test_mensagem_vazia_sem_anexo_nao_chama_servicos(client, fakes: Fakes):
    body = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": ""},
    ).json()

    assert body["status"] == "answered"
    assert body["answer"] == ("Não consegui ver a sua mensagem. Pode escrever o que você precisa?")
    assert fakes.jev.chamadas == []
    assert fakes.llm.chamadas_responder == []


def test_choice_texto_puro_tem_confianca_zero():
    assert _choice("humano", "duvida") == ("humano", 0.0, {})


def _jev_client(answers: dict[str, Any]) -> JevClient:
    settings = Settings(
        environment="pytest",
        openrouter_api_key="chave",
        jev_model="typesafe/jev-1.13",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": answers})

    return JevClient(httpx.Client(transport=httpx.MockTransport(handler)), settings)


def _resposta_intent(probabilidade_humano: float, confidence: float = 0.6) -> dict:
    return {
        "intent": {
            "type": "choice",
            "choice": "humano",
            "confidence": confidence,
            "probabilities": {
                "humano": probabilidade_humano,
                "duvida": 1.0 - probabilidade_humano,
            },
        },
        "publico": {
            "type": "choice",
            "choice": "inss",
            "confidence": 0.9,
            "probabilities": {"inss": 0.9},
        },
    }


def test_jev_usa_probabilidade_do_rotulo_e_nao_confidence():
    resultado = _jev_client(_resposta_intent(0.85)).classify("quero atendente")
    assert resultado.pediu_humano is True
    assert resultado.intent_confidence == 0.6

    resultado = _jev_client(_resposta_intent(0.70)).classify("quero atendente")
    assert resultado.pediu_humano is False


def test_jev_sem_probabilities_nao_decide():
    answers = _resposta_intent(0.85)
    del answers["intent"]["probabilities"]
    resultado = _jev_client(answers).classify("quero atendente")
    assert resultado.pediu_humano is False


def test_fluxo_usa_probabilidade_para_handoff(client, fakes: Fakes):
    fakes.jev.resultado = JevResult(
        intent="humano",
        intent_confidence=0.6,
        publico="inss",
        publico_confidence=0.9,
        probabilities={"intent": {"humano": 0.85}, "publico": {"inss": 0.9}},
    )
    body = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "quero falar com alguém"},
    ).json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "pediu_humano"


def test_fluxo_com_probabilidade_baixa_segue_para_llm(client, fakes: Fakes):
    fakes.jev.resultado = JevResult(
        intent="humano",
        intent_confidence=0.6,
        publico="inss",
        publico_confidence=0.9,
        probabilities={"intent": {"humano": 0.70}, "publico": {"inss": 0.9}},
    )
    fakes.llm.resposta = resposta_llm("Resposta do LLM")

    body = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "quero falar com alguém"},
    ).json()

    assert body["status"] == "answered"
    assert body["answer"] == "Resposta do LLM"
    assert len(fakes.llm.chamadas_responder) == 1


def test_oferta_pendente_envia_ultima_mensagem_do_agente(client, service, fakes: Fakes):
    conversa = cid()
    service.graph.update_state(
        service.config(conversa),
        {
            "status": "answered",
            "oferta_pendente": True,
            "messages": [AIMessage(content="Quer seguir com a portabilidade?")],
        },
    )

    client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "sim"},
    )

    assert fakes.jev.ofertas[-1] == "Quer seguir com a portabilidade?"


def _llm_client(handler, monkeypatch) -> LLMClient:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("saturday.services.llm.time.sleep", lambda _: None)
    settings = Settings(
        environment="pytest",
        openrouter_api_key="chave",
        llm_model="modelo-texto",
    )
    return LLMClient(httpx.Client(transport=httpx.MockTransport(handler)), settings)


def _resposta_llm() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"resposta": "Resposta certa", "resolvido": True})
                    }
                }
            ]
        },
    )


def test_llm_repete_uma_vez_apos_503(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return httpx.Response(503, request=request)
        return _resposta_llm()

    resposta = _llm_client(handler, monkeypatch).responder([{"role": "user", "content": "oi"}])
    assert resposta.resposta == "Resposta certa"
    assert chamadas["n"] == 2


def test_llm_dois_503_levantam_erro(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(503, request=request)

    with pytest.raises(LLMError):
        _llm_client(handler, monkeypatch).responder([{"role": "user", "content": "oi"}])
    assert chamadas["n"] == 2


def test_llm_400_nao_e_repetido(monkeypatch):
    chamadas = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["n"] += 1
        return httpx.Response(400, request=request)

    with pytest.raises(LLMError):
        _llm_client(handler, monkeypatch).responder([{"role": "user", "content": "oi"}])
    assert chamadas["n"] == 1
