"""Lifespan: checkpointer montado, rotas no ar e erro claro sem Postgres."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from saturday.dados.sessao import criar_engine
from saturday.settings import Settings
from saturday.web.application import get_app


def test_lifespan_monta_checkpointer_e_rotas() -> None:
    settings = Settings(environment="pytest")
    app = get_app(settings)

    with TestClient(app) as client:
        assert app.state.agent_service.checkpointer is not None

        criada = client.post(
            "/chat",
            json={"conversation_id": "lifespan-1", "message": ""},
        )
        assert criada.status_code == 200
        assert criada.json()["status"] == "answered"

        assert client.get("/conversations/lifespan-1").status_code == 200
        assert client.delete("/conversations/lifespan-1").status_code == 204
        assert client.get("/conversations/lifespan-1").status_code == 404


def test_engine_sem_database_url_falha_com_mensagem_clara() -> None:
    """Sem Postgres não existe estado de conversa: o erro tem que dizer isso."""

    settings = Settings(environment="dev")

    with pytest.raises(RuntimeError, match="SATURDAY_DATABASE_URL"):
        criar_engine(settings)
