"""C6 e iCred ligados juntos no ramo INSS (decisões 0026 e 0027, issue 22).

Dois SIMs, um por banco, cada um pedido quando a consulta daquele banco vai
acontecer. Quando o C6 já falou na conversa, o pedido do iCred sai com a
abertura que não cita a chegada do extrato. Postgres real e os dois
simuladores em processo; nenhum estado é injetado.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest
from conftest import Fakes, resultado_jev
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_icred import CPF, Jornada
from test_portabilidade_fluxo import dados_extrato

from saturday.agent.icred import textos
from saturday.agent.textos import CONSENTIMENTO_C6, CONSENTIMENTO_C6_REPETIR
from saturday.bancos.c6.cliente import ROTA_SIMULACAO, ClienteC6
from saturday.dados.modelos import Consentimento
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

# Os textos por extenso: a prova de consentimento não pode mudar sem o teste ver.
PEDIDO_ORIGINAL = (
    "Recebi o seu extrato. Antes de te passar o resultado, posso consultar também "
    "o iCred, um banco parceiro, para ver se ele tem uma condição melhor para "
    "você. Para isso vou usar o seu CPF e este número de telefone. Posso "
    "consultar? Responda *SIM* ou *NÃO*."
)
PEDIDO_DEPOIS_DO_C6 = (
    "Antes de continuar, posso consultar também "
    "o iCred, um banco parceiro, para ver se ele tem uma condição melhor para "
    "você. Para isso vou usar o seu CPF e este número de telefone. Posso "
    "consultar? Responda *SIM* ou *NÃO*."
)
PEDIDOS_DE_SIM = (CONSENTIMENTO_C6, CONSENTIMENTO_C6_REPETIR, PEDIDO_ORIGINAL, PEDIDO_DEPOIS_DO_C6)
OFERTA_C6 = "contrato novo disponível"
PORTABILIDADE = "Quer seguir com a portabilidade?"


@pytest.fixture
def jornada(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    http_c6: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    """A conversa do iCred com o C6 também ligado."""

    fakes.llm.extrato = {
        **dados_extrato(),
        "cpf": CPF,
        "numeroBeneficio": "1234567890",
        "baseCalculo": 1518.0,
    }
    jornada = Jornada(fabrica, http_icred, fakes, simulador_icred)
    settings = Settings(
        environment="pytest",
        c6_ativo=True,
        c6_base_url="http://c6",
        c6_usuario="usuario-do-simulador",
        c6_senha=SecretStr("senha-do-simulador"),
        c6_codigo_promotora="000001",
    )
    c6 = ClienteC6(http_c6, settings, fabrica, dormir=lambda _: None)
    jornada.servico.context = replace(jornada.servico.context, c6_ativo=True, c6=c6)
    return jornada


def _provas(jornada: Jornada) -> list[tuple[str, str, str]]:
    with abrir_sessao(jornada.fabrica) as sessao:
        linhas = sessao.scalars(select(Consentimento).order_by(Consentimento.id)).all()
        return [(p.tipo, p.versao, p.texto_mostrado) for p in linhas]


def _um_pedido_de_sim(resposta: str | None) -> str:
    """A mensagem do turno traz um único pedido de SIM; devolve qual."""

    texto = resposta or ""
    pedidos = [pedido for pedido in PEDIDOS_DE_SIM if pedido in texto]
    assert len(pedidos) == 1, texto
    assert texto == pedidos[0]
    return pedidos[0]


def _ate_a_recusa_do_contrato_novo(jornada: Jornada, fakes: Fakes) -> str | None:
    """Extrato, SIM do C6, oferta do contrato novo e recusa; devolve a resposta à recusa."""

    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6
    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    return jornada.falar("esse não quero").answer


def test_contrato_novo_recusado_pede_o_sim_do_icred_sem_falar_do_extrato(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    resposta = _ate_a_recusa_do_contrato_novo(jornada, fakes)

    assert _um_pedido_de_sim(resposta) == PEDIDO_DEPOIS_DO_C6
    assert simulador_icred.CHAMADAS == []

    # O CPF veio do extrato, para o C6: o SIM já abre a consulta.
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada)[-1] == ("icred_consulta", "icred-1-depois-c6", PEDIDO_DEPOIS_DO_C6)


def test_c6_sem_oferta_pede_o_sim_do_icred_na_resposta_ao_sim_do_c6(
    jornada: Jornada, simulador_c6: ModuleType
) -> None:
    simulador_c6.FALHAS.append({"rota": ROTA_SIMULACAO, "status": 500})
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    # O SIM do C6 já foi respondido: o pedido do iCred vem sozinho no turno.
    assert _um_pedido_de_sim(jornada.falar("sim").answer) == PEDIDO_DEPOIS_DO_C6

    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada)[-1] == ("icred_consulta", "icred-1-depois-c6", PEDIDO_DEPOIS_DO_C6)


def test_nao_ao_c6_pede_o_sim_do_icred_com_a_abertura_de_depois(
    jornada: Jornada, simulador_c6: ModuleType
) -> None:
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    assert _um_pedido_de_sim(jornada.falar("não").answer) == PEDIDO_DEPOIS_DO_C6

    assert ("POST", ROTA_SIMULACAO) not in simulador_c6.CHAMADAS
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    # Só a prova do iCred: o C6 foi negado.
    assert _provas(jornada) == [("icred_consulta", "icred-1-depois-c6", PEDIDO_DEPOIS_DO_C6)]


def test_resposta_ambigua_duas_vezes_ao_c6_tambem_usa_a_abertura_de_depois(
    jornada: Jornada,
) -> None:
    jornada.extrato()
    assert _um_pedido_de_sim(jornada.falar("talvez").answer) == CONSENTIMENTO_C6_REPETIR

    assert _um_pedido_de_sim(jornada.falar("talvez").answer) == PEDIDO_DEPOIS_DO_C6


def test_extrato_que_o_c6_nao_simula_recebe_o_pedido_original(
    jornada: Jornada, fakes: Fakes
) -> None:
    # Sem número do benefício o C6 nem pede o SIM: o iCred é o primeiro a falar.
    fakes.llm.extrato = {**fakes.llm.extrato, "numeroBeneficio": None, "baseCalculo": None}

    assert _um_pedido_de_sim(jornada.extrato().answer) == PEDIDO_ORIGINAL

    assert jornada.falar("sim").answer == textos.PEDIR_CPF
    assert jornada.falar(CPF).answer == textos.CONSULTANDO
    assert _provas(jornada) == [("icred_consulta", "icred-1", PEDIDO_ORIGINAL)]


def test_so_com_o_icred_ligado_o_pedido_e_a_prova_sao_os_originais(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> None:
    fakes.llm.extrato = {**dados_extrato(), "cpf": CPF, "numeroBeneficio": "1234567890"}
    jornada = Jornada(fabrica, http_icred, fakes, simulador_icred)

    assert jornada.extrato().answer == PEDIDO_ORIGINAL

    assert jornada.falar("sim").answer == textos.PEDIR_CPF
    assert jornada.falar(CPF).answer == textos.CONSULTANDO
    assert _provas(jornada) == [("icred_consulta", "icred-1", PEDIDO_ORIGINAL)]


def test_extrato_repetido_depois_do_c6_repete_a_abertura_de_depois(
    jornada: Jornada, fakes: Fakes
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)

    # O extrato de novo zera a oferta do C6, mas o C6 já falou nesta conversa.
    fakes.llm.extrato = {**fakes.llm.extrato, "numeroBeneficio": None, "baseCalculo": None}
    assert _um_pedido_de_sim(jornada.extrato().answer) == PEDIDO_DEPOIS_DO_C6


def test_contrato_novo_recusado_nao_entra_na_comparacao_com_o_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)
    estado = jornada.estado()
    recusado = Decimal(estado["c6_novo"]["valor"])
    troco = Decimal(str(estado["portability_result"]["troco_total"]))
    # O iCred fica entre os dois: perde do contrato novo recusado, ganha da portabilidade.
    liberado = troco + 1
    assert troco < liberado < recusado
    assert jornada.falar("sim").answer == textos.CONSULTANDO

    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": float(liberado)}])

    contratos: list[dict[str, Any]] = jornada.estado()["icred"]["contratos"]
    assert jornada.ultima_saida() == textos.oferta(contratos)
    assert jornada.estado()["c6_novo"]["situacao"] == "recusado"
    aceite = jornada.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")


def test_icred_que_nao_ganha_da_portabilidade_entrega_a_portabilidade(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)
    troco = jornada.estado()["portability_result"]["troco_total"]
    jornada.falar("sim")

    # Empate: o C6 ganha (decisão 0027).
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": float(troco)}])

    assert PORTABILIDADE in jornada.ultima_saida()
    assert OFERTA_C6 not in jornada.ultima_saida()
