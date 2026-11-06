"""Testes do cliente HTTP do OpenRouter (timeout total)."""

from __future__ import annotations

import pytest

from saturday.services import openrouter


class Resposta:
    def __init__(self, partes):
        self.partes = partes

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield from self.partes


def test_post_json_retorna_json(monkeypatch):
    monkeypatch.setattr(
        openrouter.httpx,
        "stream",
        lambda *a, **k: Resposta([b'{"answers": {', b'"ok": true}}']),
    )
    assert openrouter.post_json("https://exemplo", "chave", {"x": 1}, 5) == {
        "answers": {"ok": True}
    }


def test_post_json_respeita_timeout_total(monkeypatch):
    relogio = iter([0.0, 100.0])
    monkeypatch.setattr(openrouter.time, "monotonic", lambda: next(relogio))
    monkeypatch.setattr(
        openrouter.httpx,
        "stream",
        lambda *a, **k: Resposta([b'{"ok": true}']),
    )

    with pytest.raises(openrouter.OpenRouterError):
        openrouter.post_json("https://exemplo", "chave", {"x": 1}, 30)


def test_post_json_json_invalido(monkeypatch):
    monkeypatch.setattr(
        openrouter.httpx,
        "stream",
        lambda *a, **k: Resposta([b"nao e json"]),
    )
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.post_json("https://exemplo", "chave", {"x": 1}, 5)
