"""Simulação e oferta de contrato novo no C6, pelo ramo INSS (decisão 0026)."""

from __future__ import annotations

from dataclasses import replace
from types import ModuleType

import pytest
from conftest import Fakes, resultado_jev
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker
from test_c6_consentimento import CPF, _dizer
from test_portabilidade_fluxo import anexo_pdf, cid, dados_extrato, idade_anos

from saturday.agent.coleta import ler_renda
from saturday.agent.service import AgentService
from saturday.agent.textos import CONSENTIMENTO_C6, PERGUNTA_RENDA
from saturday.bancos.c6.cliente import ROTA_SIMULACAO, ClienteC6
from saturday.settings import Settings

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

SIMULOU = ("POST", ROTA_SIMULACAO)


@pytest.fixture(autouse=True)
def c6_ligado(service: AgentService, http_c6: TestClient, fabrica: sessionmaker[Session]) -> None:
    settings = Settings(
        environment="pytest",
        c6_ativo=True,
        c6_base_url="http://c6",
        c6_usuario="usuario-do-simulador",
        c6_senha=SecretStr("senha-do-simulador"),
        c6_codigo_promotora="000001",
    )
    c6 = ClienteC6(http_c6, settings, fabrica, dormir=lambda _: None)
    service.context = replace(service.context, c6_ativo=True, c6=c6)


def _extrato(
    client: TestClient, fakes: Fakes, conversa: str, *, idade: int = 64, **extras: object
) -> str:
    fakes.llm.extrato = {
        **dados_extrato(),
        "cpf": CPF,
        "numeroBeneficio": "1234567890",
        "baseCalculo": 1518.0,
        **extras,
    }
    resposta = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(idade), "uf": "MS"},
        },
    )
    return str(resposta.json()["answer"])


def test_nada_e_simulado_antes_do_sim(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    conversa = cid()
    assert _extrato(client, fakes, conversa) == CONSENTIMENTO_C6
    _dizer(client, conversa, "não")

    assert SIMULOU not in simulador_c6.CHAMADAS


def test_sim_simula_e_oferta_com_os_numeros_do_banco(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    simulador_c6.CONFIG["formato"] = "lista"
    conversa = cid()
    _extrato(client, fakes, conversa)

    corpo = _dizer(client, conversa, "sim")

    # Margem de R$ 100: parcela de R$ 99 em 108 vezes, na faixa de 1,85%.
    assert "contrato novo disponível" in corpo["answer"]
    assert "Parcela: R$ 99,00 em 108 vezes" in corpo["answer"]
    assert "Taxa: 1,85% ao mês" in corpo["answer"]
    assert simulador_c6.CHAMADAS.count(SIMULOU) == 1


def test_aceite_vai_para_o_atendente(client: TestClient, fakes: Fakes) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)
    _dizer(client, conversa, "sim")
    fakes.jev.resultado = resultado_jev(resposta_oferta="aceita")

    corpo = _dizer(client, conversa, "quero")

    assert corpo["status"] == "handoff"
    assert corpo["handoff_reason"] == "aceitou_contrato_novo"


def test_recusa_segue_para_a_portabilidade(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)
    _dizer(client, conversa, "sim")
    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")

    corpo = _dizer(client, conversa, "esse não quero")

    assert "Quer seguir com a portabilidade?" in corpo["answer"]
    fakes.jev.resultado = resultado_jev(resposta_oferta="aceita")
    assert _dizer(client, conversa, "quero")["handoff_reason"] == "aceitou_portabilidade"
    assert simulador_c6.CHAMADAS.count(SIMULOU) == 1


@pytest.mark.parametrize(
    "extras",
    [
        {"margemDisponivel": 19.0},  # margem abaixo de R$ 20
        {"margemDisponivel": 15.0, "margemUtilizada": 295.24},  # idem
        {"numeroBeneficio": None},  # sem número do benefício
    ],
)
def test_sem_condicao_de_simular_segue_para_a_portabilidade(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType, extras: dict
) -> None:
    # Sem condição de simular, o SIM nem é pedido: a portabilidade vem direto.
    assert "Quer seguir com a portabilidade?" in _extrato(client, fakes, cid(), **extras)
    assert SIMULOU not in simulador_c6.CHAMADAS


def test_extrato_sem_condicao_depois_do_sim_nao_simula_de_novo(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)
    _dizer(client, conversa, "sim")

    resposta = _extrato(client, fakes, conversa, numeroBeneficio=None, baseCalculo=None)

    assert "Quer seguir com a portabilidade?" in resposta
    assert simulador_c6.CHAMADAS.count(SIMULOU) == 1


def test_valor_abaixo_do_minimo_nao_e_ofertado(client: TestClient, fakes: Fakes) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa, margemDisponivel=21.0)

    assert "Quer seguir com a portabilidade?" in _dizer(client, conversa, "sim")["answer"]


def test_erro_do_banco_segue_para_a_portabilidade(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    simulador_c6.FALHAS.append({"rota": ROTA_SIMULACAO, "status": 500})
    conversa = cid()
    _extrato(client, fakes, conversa)

    assert "Quer seguir com a portabilidade?" in _dizer(client, conversa, "sim")["answer"]
    assert simulador_c6.CHAMADAS.count(SIMULOU) == 1  # POST não repete


def test_extrato_sem_renda_pergunta_ao_cliente(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa, baseCalculo=None)

    assert _dizer(client, conversa, "sim")["answer"] == PERGUNTA_RENDA
    assert "contrato novo disponível" in _dizer(client, conversa, "R$ 1.518,00")["answer"]


def test_extrato_de_outro_titular_pede_o_sim_de_novo(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)
    _dizer(client, conversa, "sim")

    assert _extrato(client, fakes, conversa, cpf="52998224725") == CONSENTIMENTO_C6
    assert simulador_c6.CHAMADAS.count(SIMULOU) == 1


def test_sem_beneficio_nem_renda_nao_pergunta_a_renda(client: TestClient, fakes: Fakes) -> None:
    resposta = _extrato(client, fakes, cid(), numeroBeneficio=None, baseCalculo=None)

    assert "Quer seguir com a portabilidade?" in resposta


@pytest.mark.parametrize(
    ("texto", "renda"),
    [("1.518", 1518.0), ("R$ 1.518,00", 1518.0), ("1518", 1518.0), ("1,5", None), ("inf", None)],
)
def test_renda_digitada(texto: str, renda: float | None) -> None:
    assert ler_renda(texto) == renda


def test_condicao_ilegivel_na_lista_nao_derruba_as_outras(
    client: TestClient, fakes: Fakes, simulador_c6: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulador_c6.CONFIG["formato"] = "lista"
    original = simulador_c6._condicao

    def com_recusada(corpo: dict, taxa: float, *resto: object) -> dict:
        condicao = original(corpo, taxa, *resto)
        if taxa == 1.85:
            condicao.update(client_amount=None, monthly_customer_rate="NaN")
        return dict(condicao)

    monkeypatch.setattr(simulador_c6, "_condicao", com_recusada)
    conversa = cid()
    _extrato(client, fakes, conversa)

    assert "Taxa: 1,80% ao mês" in _dizer(client, conversa, "sim")["answer"]
