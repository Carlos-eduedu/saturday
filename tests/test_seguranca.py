"""Testes de autenticação, anexos, assinatura de webhook, schemas e docs."""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import uuid
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import extrato_fake
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from saturday.portabilidade.calculo import DadosCliente, calcular_portabilidade
from saturday.portabilidade.hiscon import normalizar_extrato
from saturday.schemas import AgentReply, Cliente
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


@pytest.mark.parametrize(
    "metodo,caminho",
    [
        ("get", "/conversations/alguma"),
        ("delete", "/conversations/alguma"),
        ("post", "/conversations/alguma/release"),
    ],
)
def test_conversas_sem_chave_401(client, settings, metodo, caminho):
    settings.api_key = SecretStr("segredo")
    resposta = getattr(client, metodo)(caminho)
    assert resposta.status_code == 401
    assert resposta.json() == {"detail": "não autorizado"}


@pytest.mark.parametrize(
    "metodo,caminho",
    [
        ("get", "/conversations/com%20espaco"),
        ("delete", "/conversations/com%20espaco"),
        ("post", "/conversations/com%20espaco/release"),
    ],
)
def test_conversation_id_invalido_no_caminho_422(client, metodo, caminho):
    assert getattr(client, metodo)(caminho).status_code == 422


def test_cliente_uf_minuscula_normaliza():
    assert Cliente(uf="ms").uf == "MS"
    with pytest.raises(ValidationError):
        Cliente(uf="XX")


def test_agent_reply_serializa_portability_result_sem_mudanca():
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    resultado = calcular_portabilidade(
        normalizar_extrato(extrato_fake()),
        DadosCliente(data_nascimento=date(1962, 3, 12), uf="MS"),
        hoje,
    )
    reply = AgentReply(
        conversation_id="json-igual",
        answer="ok",
        status="answered",
        portability_result=resultado,
        timestamp=datetime.now(UTC),
    )
    assert reply.model_dump(mode="json")["portability_result"] == resultado


def test_openapi_tem_security_scheme_e_webhook():
    schema = get_app(Settings(environment="pytest")).openapi()

    schemes = schema["components"]["securitySchemes"]
    assert any(
        scheme.get("type") == "apiKey"
        and scheme.get("in") == "header"
        and scheme.get("name") == "X-API-Key"
        for scheme in schemes.values()
    )

    operacao = schema["webhooks"]["agent.reply"]["post"]
    assert operacao["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AgentReply"
    }
    cabecalhos = {
        parametro["name"]: parametro
        for parametro in operacao["parameters"]
        if parametro["in"] == "header"
    }
    assert "X-Saturday-Timestamp" in cabecalhos
    assert "X-Saturday-Signature" in cabecalhos
    assert cabecalhos["X-Saturday-Timestamp"]["description"]
    assert cabecalhos["X-Saturday-Signature"]["description"]
    assert "hmac.compare_digest" in operacao["description"]

    for caminho, metodo in [
        ("/chat", "post"),
        ("/conversations/{conversation_id}", "get"),
        ("/conversations/{conversation_id}", "delete"),
        ("/conversations/{conversation_id}/release", "post"),
    ]:
        assert schema["paths"][caminho][metodo].get("security")


def test_openapi_documenta_401_e_404_nas_rotas_de_conversa():
    schema = get_app(Settings(environment="pytest")).openapi()
    conversa = schema["paths"]["/conversations/{conversation_id}"]
    release = schema["paths"]["/conversations/{conversation_id}/release"]

    for operacao in (conversa["get"], conversa["delete"], release["post"]):
        assert "401" in operacao["responses"]
        assert "404" in operacao["responses"]


def test_delete_inexistente_retorna_404(client):
    assert client.delete("/conversations/nao-existe").status_code == 404
