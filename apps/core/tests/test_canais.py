"""Tela Canais e instâncias da Evolution geridas pelo painel (decisão 0010).

Exige Postgres; a Evolution é o simulador em HTTP real.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.evolution import webhook as parser
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.dados.modelos import Alerta, Auditoria, EventoRecebido, Instancia
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import instancias as eventos_instancias
from saturday.painel import sessoes
from saturday.settings import Settings

CAMINHO_SIMULADOR = Path(__file__).resolve().parents[3] / "simuladores" / "evolution" / "app.py"
SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
TELEFONE = "5511987654321"
OUTRO = "5521912345678"


def _porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def simulador() -> Iterator[tuple[str, ModuleType]]:
    spec = importlib.util.spec_from_file_location("simulador_evolution_canais", CAMINHO_SIMULADOR)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    porta = _porta_livre()
    server = uvicorn.Server(
        uvicorn.Config(modulo.app, host="127.0.0.1", port=porta, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started
    yield f"http://127.0.0.1:{porta}", modulo
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def settings(settings: Settings, simulador: tuple[str, ModuleType]) -> Settings:
    base, _ = simulador
    return settings.model_copy(
        update={
            "evolution_ativo": True,
            "evolution_url": base,
            "evolution_api_key": SecretStr("chave-do-simulador"),
            "evolution_webhook_token": SecretStr("token-do-simulador"),
        }
    )


@pytest.fixture
def api(client_pg: TestClient, simulador: tuple[str, ModuleType]) -> Iterator[TestClient]:
    _, modulo = simulador
    modulo.limpar()
    with httpx.Client(timeout=10.0) as http:
        client_pg.app.state.http = http  # type: ignore[attr-defined]
        yield client_pg


@pytest.fixture
def cliente(settings: Settings) -> Iterator[EvolutionClient]:
    with httpx.Client(timeout=10.0) as http:
        yield EvolutionClient(http, settings)


def _entrar(client: TestClient, fabrica: sessionmaker[Session], perfil: str) -> dict[str, str]:
    email = f"{perfil}-canais@exemplo.test"
    with abrir_sessao(fabrica) as sessao:
        sessoes.criar_usuario(sessao, email, SENHA, perfil)
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _conexao(
    estado: str, telefone: str = TELEFONE, instancia: str = "mex-vendas"
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": "connection.update",
        "instance": instancia,
        "data": {"state": estado, "statusReason": 200},
    }
    if estado == "open":
        payload["data"]["wuid"] = f"{telefone}@s.whatsapp.net"
    conexao = parser.conexao(payload)
    assert conexao is not None
    return conexao


def test_atendente_nao_ve_a_tela(api: TestClient, fabrica: sessionmaker[Session]) -> None:
    cabecalhos = _entrar(api, fabrica, "atendente")
    assert api.get("/admin/canais").status_code == 403
    resposta = api.post("/admin/canais/evolution", json={"nome": "mex-x"}, headers=cabecalhos)
    assert resposta.status_code == 403


def test_criar_lista_e_audita(
    api: TestClient,
    fabrica: sessionmaker[Session],
    simulador: tuple[str, ModuleType],
    settings: Settings,
) -> None:
    cabecalhos = _entrar(api, fabrica, "gestor")

    resposta = api.post("/admin/canais/evolution", json={"nome": "mex-vendas"}, headers=cabecalhos)
    assert resposta.status_code == 201
    assert resposta.json()["qr"].startswith("data:image/png;base64,")

    _, modulo = simulador
    webhook = modulo.INSTANCIAS["mex-vendas"]["webhook"]
    assert webhook["url"] == settings.evolution_webhook_url
    assert webhook["headers"] == {"x-webhook-token": "token-do-simulador"}
    assert "CONNECTION_UPDATE" in webhook["events"]

    canais = api.get("/admin/canais").json()
    assert canais["meta"] == [{"phone_number_id": "100000000000001"}]
    [instancia] = canais["evolution"]["instancias"]
    assert instancia["nome"] == "mex-vendas"
    assert instancia["estado"] == "connecting"

    with abrir_sessao(fabrica) as sessao:
        acoes = sessao.scalars(select(Auditoria.acao).where(Auditoria.alvo == "mex-vendas")).all()
        assert "canal_criar" in acoes


def test_nome_invalido_e_recusado(api: TestClient, fabrica: sessionmaker[Session]) -> None:
    cabecalhos = _entrar(api, fabrica, "gestor")
    resposta = api.post("/admin/canais/evolution", json={"nome": "Mex Vendas"}, headers=cabecalhos)
    assert resposta.status_code == 422


def test_reconectar_recusa_instancia_conectada(
    api: TestClient, fabrica: sessionmaker[Session], simulador: tuple[str, ModuleType]
) -> None:
    cabecalhos = _entrar(api, fabrica, "gestor")
    api.post("/admin/canais/evolution", json={"nome": "mex-vendas"}, headers=cabecalhos)
    _, modulo = simulador
    modulo.INSTANCIAS["mex-vendas"].update(estado="open", telefone=TELEFONE)

    resposta = api.post("/admin/canais/evolution/mex-vendas/conectar", headers=cabecalhos)
    assert resposta.status_code == 409


def test_reconectar_reaplica_configuracao_e_devolve_qr(
    api: TestClient, fabrica: sessionmaker[Session], simulador: tuple[str, ModuleType]
) -> None:
    cabecalhos = _entrar(api, fabrica, "gestor")
    _, modulo = simulador
    # Criada fora do painel, sem webhook.
    modulo.INSTANCIAS["mex-dev"] = {"estado": "close", "telefone": "", "webhook": None}

    resposta = api.post("/admin/canais/evolution/mex-dev/conectar", headers=cabecalhos)
    assert resposta.status_code == 200
    assert resposta.json()["qr"]
    assert modulo.INSTANCIAS["mex-dev"]["webhook"]["enabled"] is True


def test_conectar_fixa_o_telefone(fabrica: sessionmaker[Session], cliente: EvolutionClient) -> None:
    eventos_instancias.aplicar(fabrica, cliente, _conexao("open"))
    eventos_instancias.aplicar(fabrica, cliente, _conexao("open"))

    with abrir_sessao(fabrica) as sessao:
        fixada = sessao.get(Instancia, "mex-vendas")
        assert fixada is not None and fixada.telefone == "11987654321"
        assert not sessao.scalars(select(Alerta)).all()


def test_outro_celular_desconecta_e_alerta(
    fabrica: sessionmaker[Session],
    cliente: EvolutionClient,
    simulador: tuple[str, ModuleType],
) -> None:
    _, modulo = simulador
    modulo.limpar()
    eventos_instancias.aplicar(fabrica, cliente, _conexao("open"))
    modulo.INSTANCIAS["mex-vendas"] = {"estado": "open", "telefone": OUTRO, "webhook": None}

    eventos_instancias.aplicar(fabrica, cliente, _conexao("open", telefone=OUTRO))

    assert modulo.INSTANCIAS["mex-vendas"]["estado"] == "close"
    with abrir_sessao(fabrica) as sessao:
        [alerta] = sessao.scalars(select(Alerta)).all()
        assert alerta.tipo == eventos_instancias.ALERTA_NUMERO_TROCADO
        assert alerta.detalhe is not None
        assert "912345678" not in str(alerta.detalhe), "telefone sem máscara no alerta"


def test_queda_vira_um_alerta_por_instancia(
    fabrica: sessionmaker[Session], cliente: EvolutionClient
) -> None:
    eventos_instancias.aplicar(fabrica, cliente, _conexao("close"))
    eventos_instancias.aplicar(fabrica, cliente, _conexao("refused"))

    with abrir_sessao(fabrica) as sessao:
        alertas = sessao.scalars(select(Alerta)).all()
        assert [a.tipo for a in alertas] == [eventos_instancias.ALERTA_DESCONECTADA]


def test_apagar_solta_o_telefone(
    api: TestClient,
    fabrica: sessionmaker[Session],
    cliente: EvolutionClient,
    simulador: tuple[str, ModuleType],
) -> None:
    cabecalhos = _entrar(api, fabrica, "gestor")
    _, modulo = simulador
    modulo.INSTANCIAS["mex-vendas"] = {"estado": "open", "telefone": TELEFONE, "webhook": None}
    eventos_instancias.aplicar(fabrica, cliente, _conexao("open"))

    assert api.delete("/admin/canais/evolution/mex-vendas", headers=cabecalhos).status_code == 204

    assert "mex-vendas" not in modulo.INSTANCIAS
    with abrir_sessao(fabrica) as sessao:
        assert sessao.get(Instancia, "mex-vendas") is None


def test_webhook_de_conexao_vai_para_a_fila(
    api: TestClient, fabrica: sessionmaker[Session]
) -> None:
    payload = {
        "event": "connection.update",
        "instance": "qualquer",
        "data": {"state": "close", "statusReason": 401},
    }
    resposta = api.post(
        "/webhooks/evolution", json=payload, headers={"x-webhook-token": "token-do-simulador"}
    )
    assert resposta.status_code == 200

    with abrir_sessao(fabrica) as sessao:
        [linha] = sessao.scalars(select(EventoRecebido)).all()
        assert linha.payload == {
            "tipo": "conexao",
            "instancia": "qualquer",
            "estado": "close",
            "telefone": "",
            "motivo": 401,
        }
