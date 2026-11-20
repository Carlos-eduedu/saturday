"""Aba Integrações: os parceiros, só leitura, sem o valor de nenhum segredo."""

from __future__ import annotations

from typing import Any

from conftest import entrar_como
from fastapi.testclient import TestClient
from pydantic import SecretStr

from saturday.painel.parceiros import parceiros
from saturday.settings import Settings

ROTA = "/admin/gestao/parceiros"


def _por_id(settings: Settings) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in parceiros(settings)}


def test_situacao_de_cada_parceiro(settings: Settings) -> None:
    settings.granatech_ativo = True  # ativo sem a chave
    settings.c6_ativo = False
    p = _por_id(settings)
    assert p["meta"]["situacao"] == "ligado"
    assert p["meta"]["em_canais"] is True
    assert p["granatech"]["situacao"] == "falta_chave"
    assert p["granatech"]["segredos"] == {"chave_api": False, "token_webhook": False}
    assert p["c6"]["situacao"] == "desligado"
    assert p["brasilapi"] == p["brasilapi"] | {"situacao": "ligado", "sempre": True}
    assert p["brasilapi"]["host"] == "brasilapi.com.br"
    # Sempre chamado, mas sem chave no ambiente de teste.
    assert p["openrouter"]["situacao"] == "falta_chave"


def test_parceiro_ligado_com_todas_as_chaves(settings: Settings) -> None:
    settings.granatech_ativo = True
    settings.granatech_chave_api = SecretStr("chave-ficticia")
    settings.granatech_webhook_token = SecretStr("token-ficticio")
    assert _por_id(settings)["granatech"]["situacao"] == "ligado"


def test_host_sem_credencial_embutida(settings: Settings) -> None:
    settings.s3_endpoint = "https://usuario:senha-ficticia@minio.interno:9000/caminho"
    assert _por_id(settings)["storage"]["host"] == "minio.interno:9000"


def test_so_o_gestor_ve_e_nenhum_segredo_sai(client_pg: TestClient, fabrica: Any) -> None:
    entrar_como(client_pg, fabrica, "atendente")
    assert client_pg.get(ROTA).status_code == 403

    client_pg.cookies.clear()
    entrar_como(client_pg, fabrica, "gestor")
    resposta = client_pg.get(ROTA)
    assert resposta.status_code == 200
    assert [p["id"] for p in resposta.json()] == [
        "meta",
        "evolution",
        "granatech",
        "c6",
        "icred",
        "brasilapi",
        "openrouter",
        "transcricao",
        "storage",
    ]
    # Os valores do fixture `settings` não podem aparecer em lugar nenhum.
    for valor in ("token-de-teste", "segredo-de-teste", "verificacao-de-teste"):
        assert valor not in resposta.text
