"""Testes do cliente HTTP do OpenRouter (timeout total)."""

from __future__ import annotations

import httpx
import pytest

from saturday.services import openrouter
from saturday.services.openrouter import OpenRouterClient, OpenRouterError


def _client(handler) -> OpenRouterClient:  # type: ignore[no-untyped-def]
    return OpenRouterClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "chave",
    )


def test_post_json_retorna_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {"ok": True}})

    client = _client(handler)
    try:
        assert client.post_json("https://exemplo", {"x": 1}, 5) == {"answers": {"ok": True}}
    finally:
        client._http.close()  # type: ignore[attr-defined]  # fecha o cliente do teste


def test_post_json_respeita_timeout_total(monkeypatch):
    relogio = iter([0.0, 100.0])
    monkeypatch.setattr(openrouter.time, "monotonic", lambda: next(relogio))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"ok": true}')

    client = _client(handler)
    try:
        with pytest.raises(OpenRouterError):
            client.post_json("https://exemplo", {"x": 1}, 30)
    finally:
        client._http.close()  # type: ignore[attr-defined]


def test_post_json_json_invalido():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"nao e json")

    client = _client(handler)
    try:
        with pytest.raises(OpenRouterError):
            client.post_json("https://exemplo", {"x": 1}, 5)
    finally:
        client._http.close()  # type: ignore[attr-defined]
