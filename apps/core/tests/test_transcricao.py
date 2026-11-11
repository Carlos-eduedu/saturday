"""Cliente de transcrição: contrato do endpoint compatível com OpenAI."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from saturday.services.transcricao import Transcritor
from saturday.settings import Settings


def _transcritor(handler: Any, **extras: Any) -> Transcritor:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Transcritor(
        http,
        Settings(
            environment="pytest",
            transcricao_api_key=SecretStr("chave"),
            transcricao_modelo="whisper-1",
            transcricao_base_url="https://transcricao.test/v1",
            **extras,
        ),
    )


def test_transcrever_envia_multipart_e_devolve_texto() -> None:
    visto: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        visto["url"] = str(request.url)
        visto["auth"] = request.headers.get("authorization")
        visto["corpo"] = request.read()
        return httpx.Response(200, json={"text": "  quero portabilidade  "})

    texto = _transcritor(handler).transcrever(b"OggS", "audio/ogg")

    assert texto == "quero portabilidade"
    assert visto["url"] == "https://transcricao.test/v1/audio/transcriptions"
    assert visto["auth"] == "Bearer chave"
    assert b'name="model"' in visto["corpo"]
    assert b"whisper-1" in visto["corpo"]


def test_transcrever_sem_chave_fica_desligado() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    transcritor = Transcritor(http, Settings(environment="pytest"))
    assert transcritor.habilitado is False
    assert transcritor.transcrever(b"x", "audio/ogg") is None


def test_transcrever_erro_do_provedor_devolve_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "x"})

    assert _transcritor(handler).transcrever(b"x", "audio/ogg") is None


def test_transcrever_falha_de_rede_devolve_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede")

    assert _transcritor(handler).transcrever(b"x", "audio/ogg") is None
