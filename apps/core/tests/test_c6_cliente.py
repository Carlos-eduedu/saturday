"""Cliente do C6 contra o simulador (em processo) e Postgres."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.c6.cliente import (
    ROTA_LINK,
    ROTA_PROPOSTA,
    ROTA_SIMULACAO,
    ClienteC6,
    ErroC6,
    ErroIncerto,
    PedidoSimulacao,
    corpo_da_simulacao,
)
from saturday.dados.modelos import ChamadaExterna
from saturday.settings import Settings

# O cliente passa o timeout por requisição; o TestClient ignora e avisa.
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

NOVO = PedidoSimulacao(
    operacao="NOVA",
    cpf="00189004967",
    beneficio="1234567890",
    nascimento=date(1956, 11, 29),
    renda=Decimal("4000"),
    parcelas=96,
    valor_solicitado=Decimal("6900"),
)
REFIN = PedidoSimulacao(
    operacao="REFINANCIAMENTO",
    cpf="00189004967",
    beneficio="1234567890",
    nascimento=date(1956, 11, 29),
    renda=Decimal("4000"),
    parcelas=96,
    valor_parcela=Decimal("150.90"),
    contratos=("900123456789",),
)
# Só os blocos que o simulador confere; o corpo completo é da fase de digitação.
PROPOSTA = {
    "operation_type": "NOVA",
    "origin": {"promoter_code": "000001"},
    "credit_condition": {"installment_quantity": 96},
    "payment": {"bank_code": "341"},
    "client": {"name": "TESTE SILVA"},
}


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def esperas() -> list[float]:
    return []


@pytest.fixture
def c6(
    http_c6: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> ClienteC6:
    settings = Settings(
        environment="pytest",
        c6_ativo=True,
        c6_base_url="http://c6",
        c6_usuario="usuario-do-simulador",
        c6_senha=SecretStr("senha-do-simulador"),
        c6_codigo_promotora="000001",
    )
    return ClienteC6(http_c6, settings, fabrica, relogio=relogio, dormir=esperas.append)


def test_simula_contrato_novo_e_registra_so_a_rota(
    c6: ClienteC6, fabrica: sessionmaker[Session]
) -> None:
    simulacao = c6.simular(NOVO)

    assert simulacao.parcelas == 96
    assert simulacao.principal == Decimal("6900.0")
    assert simulacao.taxa_mensal == Decimal("1.8")
    assert simulacao.valor_cliente == simulacao.principal - simulacao.iof
    assert simulacao.convenio and simulacao.produto
    with fabrica() as sessao:
        chamadas = sessao.scalars(select(ChamadaExterna).order_by(ChamadaExterna.id)).all()
    assert [(c.servico, c.metodo, c.rota, c.status_http) for c in chamadas] == [
        ("c6", "POST", "/auth/token", 200),
        ("c6", "POST", ROTA_SIMULACAO, 200),
    ]


def test_refinanciamento_desconta_o_saldo_dos_contratos(
    c6: ClienteC6, simulador_c6: ModuleType
) -> None:
    simulacao = c6.simular(REFIN)

    assert simulacao.parcela == Decimal("150.9")
    liquido = simulacao.principal - simulacao.iof
    assert simulacao.valor_cliente == liquido - Decimal(str(simulador_c6.CONFIG["saldo_refin"]))
    assert simulacao.bruto["refinancing"][0]["proposal_operation_number"] == "900123456789"


def test_corpo_da_simulacao_segue_o_manual() -> None:
    corpo = corpo_da_simulacao(REFIN, "000001")

    assert corpo == {
        "operation_type": "REFINANCIAMENTO",
        "product_type_code": "0002",
        "simulation_type": "POR_VALOR_PARCELA",
        "formalization_subtype": "DIGITAL_WEB",
        "promoter_code": "000001",
        "covenant_group": "INSS",
        "public_agency": "000001",
        "installment_quantity": 96,
        "installment_amount": 150.9,
        "client": {
            "tax_identifier": "00189004967",
            "enrollment": "1234567890",
            "birth_date": "1956-11-29",
            "income_amount": 4000.0,
        },
        "refinancing_contracts": ["900123456789"],
    }


@pytest.mark.parametrize(
    "mudanca",
    [
        {"valor_parcela": Decimal("100")},  # os dois valores
        {"valor_solicitado": None},  # nenhum
        {"contratos": ("900123456789",)},  # contrato novo com contrato a refinanciar
        {"operacao": "REFINANCIAMENTO"},  # refinanciamento sem contrato
    ],
)
def test_pedido_incoerente_nem_sai(mudanca: dict[str, Any]) -> None:
    pedido = PedidoSimulacao(**{**NOVO.__dict__, **mudanca})

    with pytest.raises(ValueError):
        corpo_da_simulacao(pedido, "000001")


def test_token_fica_em_cache_e_renova_antes_de_vencer(
    c6: ClienteC6, simulador_c6: ModuleType, relogio: Relogio
) -> None:
    c6.simular(NOVO)
    c6.simular(NOVO)
    assert len(simulador_c6.LOGINS) == 1

    relogio.agora += simulador_c6.CONFIG["expira_s"] - 30
    c6.simular(NOVO)
    assert len(simulador_c6.LOGINS) == 2


def test_401_renova_o_token_e_repete_uma_vez(c6: ClienteC6, simulador_c6: ModuleType) -> None:
    c6.simular(NOVO)
    simulador_c6.TOKENS.clear()

    assert c6.simular(NOVO).parcelas == 96
    assert len(simulador_c6.LOGINS) == 2


def test_inclui_consulta_e_pega_o_link(c6: ClienteC6) -> None:
    numero = c6.incluir(PROPOSTA)

    assert c6.consultar(numero)["proposal_number"] == numero
    link = c6.link_formalizacao(numero)
    assert link.url.endswith(numero) and link.ativo


def test_inclusao_com_500_e_incerta_e_nao_repete(c6: ClienteC6, simulador_c6: ModuleType) -> None:
    simulador_c6.FALHAS.append({"rota": ROTA_PROPOSTA, "status": 500, "registrar": True})

    with pytest.raises(ErroIncerto):
        c6.incluir(PROPOSTA)

    assert simulador_c6.CHAMADAS.count(("POST", ROTA_PROPOSTA)) == 1
    assert len(simulador_c6.PROPOSTAS) == 1  # o banco fez; só a resposta se perdeu


def test_inclusao_recusada_e_erro_comprovado(c6: ClienteC6) -> None:
    with pytest.raises(ErroC6) as erro:
        c6.incluir({"operation_type": "NOVA"})

    assert erro.value.status == 400
    assert not isinstance(erro.value, ErroIncerto)


def test_get_repete_uma_vez_em_5xx(
    c6: ClienteC6, simulador_c6: ModuleType, esperas: list[float]
) -> None:
    numero = c6.incluir(PROPOSTA)
    simulador_c6.FALHAS.append({"rota": ROTA_LINK, "status": 503})

    assert c6.link_formalizacao(numero).ativo
    assert len(esperas) == 1


def test_timeout_no_post_e_incerto(
    fabrica: sessionmaker[Session], relogio: Relogio, esperas: list[float]
) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in_seconds": 1199})
        raise httpx.ReadTimeout("sem resposta", request=request)

    settings = Settings(environment="pytest", c6_base_url="http://c6")
    http = httpx.Client(transport=httpx.MockTransport(responder))
    c6 = ClienteC6(http, settings, fabrica, relogio=relogio, dormir=esperas.append)

    with pytest.raises(ErroIncerto):
        c6.incluir(PROPOSTA)
    with pytest.raises(ErroC6) as erro:
        c6.consultar("960000001")
    assert not isinstance(erro.value, ErroIncerto)
