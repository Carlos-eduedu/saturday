"""Limite de tamanho do corpo da requisição.

`POST /chat` aceita anexo em base64, então o corpo pode ser grande — mas não
ilimitado. Sem teto, um cliente (ou um erro de cliente) derruba o processo por
memória antes de qualquer validação de schema.

O limite é checado no `Content-Length` e recontado durante a leitura, para o caso
de corpo em partes (`Transfer-Encoding: chunked`), que não declara tamanho.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

LIMITE_CORPO_BYTES = 20 * 1024 * 1024
MENSAGEM_413 = '{"detail": "corpo da requisição acima de 20 MB"}'.encode()


def _cabecalho(scope: MutableMapping[str, Any], nome: bytes) -> bytes | None:
    cabecalhos: list[tuple[bytes, bytes]] = scope.get("headers") or []
    for chave, valor in cabecalhos:
        if chave.lower() == nome:
            return valor
    return None


async def _responder_413(send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(MENSAGEM_413)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": MENSAGEM_413})


class LimiteDeCorpo:
    """Middleware ASGI que recusa corpo acima de ``LIMITE_CORPO_BYTES``."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        declarado = _cabecalho(scope, b"content-length")
        if declarado is not None and declarado.isdigit() and int(declarado) > LIMITE_CORPO_BYTES:
            await _responder_413(send)
            return

        recebido = 0
        estourou = False

        async def enviar(mensagem: dict[str, Any]) -> None:
            # Depois do estouro, o 413 já foi enviado: descarta o que a
            # aplicação tentar responder em seguida.
            if estourou:
                return
            await send(mensagem)

        async def receber() -> dict[str, Any]:
            nonlocal recebido, estourou
            if estourou:
                return {"type": "http.disconnect"}
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                recebido += len(mensagem.get("body") or b"")
                if recebido > LIMITE_CORPO_BYTES:
                    estourou = True
                    # Responde agora e encerra a leitura: a aplicação não
                    # chega a processar um corpo parcial.
                    await _responder_413(send)
                    return {"type": "http.disconnect"}
            return mensagem

        await self.app(scope, receber, enviar)
