"""Script de evidências da homologação Granatech, rodado contra o simulador."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "homologacao_granatech.py"
CHAVE = "chave-do-simulador"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("homologacao_granatech", SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["homologacao_granatech"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def granatech(simulador_granatech: ModuleType) -> Iterator[TestClient]:
    with TestClient(simulador_granatech.app, base_url="http://granatech") as cliente:
        yield cliente


def _saturday(eventos: dict[str, list[dict[str, Any]]]) -> httpx.Client:
    """O Saturday falso: devolve os eventos "recebidos" por id e exige a chave."""

    def responder(request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-API-Key") != "chave-saturday":
            return httpx.Response(401)
        id_externo = request.url.path.rsplit("/", 1)[-1]
        payload = eventos.get(id_externo, [{"status": "SUCCESS", "id": id_externo}])
        return httpx.Response(200, json=[{"payload": p} for p in payload])

    return httpx.Client(base_url="http://saturday", transport=httpx.MockTransport(responder))


def test_gera_as_evidencias_das_duas_fases(
    script: ModuleType, granatech: TestClient, simulador_granatech: ModuleType, tmp_path: Path
) -> None:
    homologacao = script.Homologacao(
        granatech=granatech,
        saturday=_saturday({}),
        chave=CHAVE,
        api_key="chave-saturday",
        saida=tmp_path,
        espera_webhook_s=0,
        dormir=lambda _s: None,
    )
    relatorio = homologacao.rodar().read_text(encoding="utf-8")

    itens = [(e.fase, e.item, e.ok) for e in homologacao.evidencias]
    assert itens == [
        ("Fase 1", "Consulta via resposta direta", True),
        ("Fase 1", "Consulta via notificação do webhook", True),
        ("Fase 1", "Simulação com seguro", True),
        ("Fase 1", "Simulação sem seguro", True),
        ("Fase 2", "Contratação 1 com sucesso", True),
        ("Fase 2", "Contratação 2 com sucesso", True),
        ("Fase 2", "Erro de contratação", True),
    ]
    assert "Parou antes do fim" not in relatorio
    # Na dev o "sem seguro" é ignorado; o relatório diz isso.
    assert "devolveu o bloco com seguro" in relatorio
    assert len(simulador_granatech.PROPOSTAS) == 2
    assert all("dados_tomador" in p for p in simulador_granatech.PROPOSTAS.values())

    # Nenhum arquivo traz a chave ou o token.
    for arquivo in tmp_path.iterdir():
        texto = arquivo.read_text(encoding="utf-8")
        assert CHAVE not in texto
        assert not any(token in texto for token in simulador_granatech.TOKENS)
    erro = json.loads(next(tmp_path.glob("*-proposta-com-erro.json")).read_text())
    assert 400 <= erro["status_http"] < 500


def test_webhook_que_nao_chega_fica_registrado(
    script: ModuleType, granatech: TestClient, tmp_path: Path
) -> None:
    homologacao = script.Homologacao(
        granatech=granatech,
        saturday=_saturday({}),
        chave=CHAVE,
        api_key="chave-errada",
        saida=tmp_path,
        espera_webhook_s=0,
        dormir=lambda _s: None,
    )
    relatorio = homologacao.rodar().read_text(encoding="utf-8")
    webhook = [e for e in homologacao.evidencias if "webhook" in e.item]
    assert webhook and not webhook[0].ok
    assert "**falhou**" in relatorio


def test_recusa_a_producao(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    for nome, valor in {
        "SATURDAY_GRANATECH_BASE_URL": "https://api.granatech.com.br",
        "SATURDAY_GRANATECH_CHAVE_API": "x",
        "SATURDAY_URL_HOMOLOG": "https://saturday",
        "SATURDAY_API_KEY": "y",
    }.items():
        monkeypatch.setenv(nome, valor)
    assert script.main() == 2


def test_exige_as_variaveis(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SATURDAY_GRANATECH_CHAVE_API", raising=False)
    assert script.main() == 2
