"""Testes de autenticação, anexos, assinatura de webhook, schemas e docs."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from saturday.services import anexos as anexos_service
from saturday.services.anexos import AnexoInvalido, AnexosClient
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings
from saturday.web.application import get_app


def cid() -> str:
    return f"seguranca-{uuid.uuid4()}"


def _settings(**extras: Any) -> Settings:
    return Settings(environment="pytest", **extras)


def _resolver(ip: str):
    def resolver(*args: Any, **kwargs: Any) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    return resolver


def _sem_rede(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"chamada inesperada: {request.method} {request.url}")


def test_chat_sem_chave_401(client, settings):
    settings.api_key = SecretStr("segredo")
    r = client.post("/chat", json={"conversation_id": cid(), "message": "oi"})
    assert r.status_code == 401
    assert r.json() == {"detail": "não autorizado"}


def test_chat_com_chave_errada_401(client, settings):
    settings.api_key = SecretStr("segredo")
    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "oi"},
        headers={"X-API-Key": "errada"},
    )
    assert r.status_code == 401


def test_chat_com_chave_certa_200(client, settings):
    settings.api_key = SecretStr("segredo")
    r = client.post(
        "/chat",
        json={"conversation_id": cid(), "message": "oi"},
        headers={"X-API-Key": "segredo"},
    )
    assert r.status_code == 200


def test_health_sem_chave_200(client, settings):
    settings.api_key = SecretStr("segredo")
    assert client.get("/health").status_code == 200


def test_anexo_host_fora_da_lista_recusado():
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(anexo_dominios=["permitido.test"]),
    )
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo({"url": "https://outro.test/extrato.jpg", "mime_type": "image/jpeg"})


def test_anexo_http_recusado():
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(anexo_dominios=["arquivo.test"]),
    )
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo({"url": "http://arquivo.test/extrato.jpg", "mime_type": "image/jpeg"})


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5"])
def test_anexo_ip_interno_recusado(monkeypatch, ip):
    monkeypatch.setattr(anexos_service.socket, "getaddrinfo", _resolver(ip))
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(anexo_dominios=["arquivo.test"]),
    )
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo({"url": "https://arquivo.test/extrato.jpg", "mime_type": "image/jpeg"})


def test_anexo_redirecionamento_recusado(monkeypatch):
    monkeypatch.setattr(anexos_service.socket, "getaddrinfo", _resolver("93.184.216.34"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://arquivo.test/outro.jpg"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        avec = AnexosClient(http, _settings(anexo_dominios=["arquivo.test"]))
        with pytest.raises(AnexoInvalido):
            avec.carregar_anexo(
                {"url": "https://arquivo.test/extrato.jpg", "mime_type": "image/jpeg"}
            )


def test_anexo_streaming_acima_do_limite_abortado(monkeypatch):
    monkeypatch.setattr(anexos_service.socket, "getaddrinfo", _resolver("93.184.216.34"))

    def corpo():
        for _ in range(11):
            yield b"x" * (1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=corpo())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        avec = AnexosClient(http, _settings(anexo_dominios=["arquivo.test"]))
        with pytest.raises(AnexoInvalido):
            avec.carregar_anexo(
                {"url": "https://arquivo.test/extrato.pdf", "mime_type": "application/pdf"}
            )


def test_anexo_content_length_acima_do_limite_recusado_sem_ler(monkeypatch):
    monkeypatch.setattr(anexos_service.socket, "getaddrinfo", _resolver("93.184.216.34"))
    lido = {"sim": False}

    def corpo():
        lido["sim"] = True
        yield b"x"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(11 * 1024 * 1024)},
            content=corpo(),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        avec = AnexosClient(http, _settings(anexo_dominios=["arquivo.test"]))
        with pytest.raises(AnexoInvalido):
            avec.carregar_anexo(
                {"url": "https://arquivo.test/extrato.pdf", "mime_type": "application/pdf"}
            )
    assert lido["sim"] is False


def test_webhook_assinatura_confere():
    capturado: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado["request"] = request
        return httpx.Response(200)

    settings = _settings(
        webhook_url="https://webhook.test/agent",
        webhook_secret="segredo",  # noqa: S106  # segredo de teste
    )
    payload = {"conversation_id": "x", "status": "answered"}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert WebhookClient(http, settings).enviar(payload) is True

    request = capturado["request"]
    timestamp = request.headers["X-Saturday-Timestamp"]
    esperado = hmac.new(
        b"segredo",
        f"{timestamp}.".encode() + request.content,
        hashlib.sha256,
    ).hexdigest()
    assert request.headers["X-Saturday-Signature"] == f"sha256={esperado}"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"conversation_id": cid(), "message": "oi", "cliente": {"uf": "XX"}},
        {
            "conversation_id": cid(),
            "message": "oi",
            "attachments": [{"base64": "eA==", "mime_type": "text/plain"}],
        },
        {"conversation_id": cid(), "message": "x" * 4001},
        {"conversation_id": "com espaço", "message": "oi"},
    ],
)
def test_schemas_invalidos_retornam_422(client, payload):
    assert client.post("/chat", json=payload).status_code == 422


def test_prod_sem_docs():
    settings = Settings(
        environment="prod",
        api_key="segredo",
        openrouter_api_key="chave",
        llm_model="texto",
        vision_model="visao",
    )
    app = get_app(settings)
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
