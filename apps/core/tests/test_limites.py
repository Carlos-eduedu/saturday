"""Limite do corpo da requisição (20 MB)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from saturday.web.limites import LIMITE_CORPO_BYTES, LimiteDeCorpo


class AppQueLeTudo:
    """Consome o corpo até o fim e responde 200. Registra se foi chamado."""

    def __init__(self) -> None:
        self.corpo = b""
        self.responder = True

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        while True:
            mensagem = await receive()
            if mensagem["type"] != "http.request":
                break
            self.corpo += mensagem.get("body") or b""
            if not mensagem.get("more_body"):
                break
        if self.responder:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _scope(content_length: bytes | None) -> dict[str, Any]:
    cabecalhos = [] if content_length is None else [(b"content-length", content_length)]
    return {"type": "http", "method": "POST", "path": "/chat", "headers": cabecalhos}


def _rodar(app: Any, scope: dict[str, Any], partes: list[bytes]) -> list[dict[str, Any]]:
    enviado: list[dict[str, Any]] = []

    async def send(mensagem: dict[str, Any]) -> None:
        enviado.append(mensagem)

    fila = list(partes)

    async def receive() -> dict[str, Any]:
        if not fila:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": fila.pop(0), "more_body": bool(fila)}

    asyncio.run(app(scope, receive, send))
    return enviado


def test_content_length_acima_do_limite_recusa_sem_ler_o_corpo() -> None:
    interno = AppQueLeTudo()
    enviado = _rodar(
        LimiteDeCorpo(interno),
        _scope(str(LIMITE_CORPO_BYTES + 1).encode()),
        [b"nao deveria ser lido"],
    )

    assert enviado[0]["status"] == 413
    assert interno.corpo == b""  # a aplicação nunca rodou


def test_corpo_em_partes_acima_do_limite_recusa() -> None:
    interno = AppQueLeTudo()
    parte = b"x" * (1024 * 1024)
    enviado = _rodar(
        LimiteDeCorpo(interno),
        _scope(None),
        [parte] * (LIMITE_CORPO_BYTES // len(parte) + 2),
    )

    assert enviado[0]["status"] == 413
    assert len(interno.corpo) <= LIMITE_CORPO_BYTES


def test_corpo_dentro_do_limite_passa() -> None:
    interno = AppQueLeTudo()
    enviado = _rodar(LimiteDeCorpo(interno), _scope(None), [b"oi"])

    assert enviado[0]["status"] == 200
    assert interno.corpo == b"oi"


def test_rota_chat_recusa_corpo_de_21_mb(client: TestClient) -> None:
    """O limite tem que estar montado na aplicação, não só existir."""

    resposta = client.post(
        "/chat",
        content=b"x" * (LIMITE_CORPO_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert resposta.status_code == 413
