"""Lifespan: checkpointer montado, rotas no ar e erro claro sem Postgres."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

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


def _completo(**extras: object) -> Settings:
    """Configuração mínima que passa nas validações, exceto o que o teste variar."""

    base: dict[str, object] = {
        "openrouter_api_key": SecretStr("chave"),
        "llm_model": "texto",
        "vision_model": "visao",
        "database_url": SecretStr("postgresql://u:p@127.0.0.1:1/x"),
        "s3_bucket": "bucket",
        "whatsapp_token": SecretStr("token"),
        "whatsapp_app_secret": SecretStr("segredo"),
        "whatsapp_verify_token": SecretStr("verificacao"),
        "whatsapp_numeros": ["100000000000001"],
    }
    base.update(extras)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("ambiente", ["homolog", "prod"])
def test_homolog_e_prod_sem_api_key_nao_sobem(ambiente: str) -> None:
    settings = _completo(environment=ambiente)

    with pytest.raises(RuntimeError, match="SATURDAY_API_KEY"):
        settings.validar_para_subir()


def test_dev_sem_api_key_so_avisa() -> None:
    settings = _completo(environment="dev")

    settings.validar_para_subir()  # não levanta


def test_homolog_com_api_key_sobe() -> None:
    settings = _completo(environment="homolog", api_key=SecretStr("chave"))

    settings.validar_para_subir()
