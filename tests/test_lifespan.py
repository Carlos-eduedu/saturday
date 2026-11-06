"""Teste do lifespan real: SQLite, checkpointer e rotas montadas."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from saturday.settings import Settings
from saturday.web.application import get_app


def test_lifespan_monta_checkpointer_e_rotas(tmp_path):
    settings = Settings(
        environment="pytest",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
    )
    app = get_app(settings)

    with TestClient(app) as client:
        assert app.state.agent_service.checkpointer is not None
        assert (tmp_path / "checkpoints.sqlite").exists()

        criada = client.post(
            "/chat",
            json={"conversation_id": "lifespan-1", "message": ""},
        )
        assert criada.status_code == 200
        assert criada.json()["status"] == "answered"

        assert client.get("/conversations/lifespan-1").status_code == 200
        assert client.delete("/conversations/lifespan-1").status_code == 204
        assert client.get("/conversations/lifespan-1").status_code == 404


def test_lifespan_erro_claro_quando_caminho_do_sqlite_e_invalido(tmp_path):
    arquivo = tmp_path / "nao-e-diretorio"
    arquivo.write_text("x")
    settings = Settings(
        environment="pytest",
        checkpoint_path=arquivo / "checkpoints.sqlite",
    )
    app = get_app(settings)

    with (
        pytest.raises(RuntimeError, match="Não foi possível abrir o SQLite"),
        TestClient(app),
    ):
        pass
