"""C6 e iCred ligados juntos no ramo INSS (decisões 0026 e 0027, issue 22).

Dois SIMs, um por banco, cada um pedido quando a consulta daquele banco vai
acontecer. Quando o C6 já falou na conversa, o pedido do iCred sai com a
abertura que não cita a chegada do extrato. Postgres real e os dois
simuladores em processo; nenhum estado é injetado.
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest
from conftest import Fakes, resultado_jev
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_icred import CPF, RESPOSTA_DA_DUVIDA, Jornada
from test_portabilidade_fluxo import dados_extrato

from saturday.agent.icred import textos
from saturday.agent.service import Oferta, ofertas_da_conversa
from saturday.agent.textos import (
    CONSENTIMENTO_C6,
    CONSENTIMENTO_C6_REPETIR,
    MENSAGEM_EXTRATO_ILEGIVEL,
    MENSAGEM_SEM_TEXTO,
)
from saturday.bancos.c6.cliente import ROTA_SIMULACAO, ClienteC6
from saturday.dados.modelos import Consentimento, ConsultaIcred, Mensagem
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import icred as job
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


@pytest.mark.parametrize("banco_fora_do_ar", [True, False])
def test_c6_sem_oferta_pede_o_sim_do_icred_na_resposta_ao_sim_do_c6(
    jornada: Jornada, fakes: Fakes, simulador_c6: ModuleType, banco_fora_do_ar: bool
) -> None:
    if banco_fora_do_ar:
        simulador_c6.FALHAS.append({"rota": ROTA_SIMULACAO, "status": 500})
    else:
        # Margem de R$ 21: o banco simula, mas o valor fica abaixo do mínimo.
        fakes.llm.extrato = {**fakes.llm.extrato, "margemDisponivel": 21.0}
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

    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada) == [("icred_consulta", "icred-1-depois-c6", PEDIDO_DEPOIS_DO_C6)]


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
    assert troco > 0
    jornada.falar("sim")

    # Empate: o C6 ganha (decisão 0027).
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": float(troco)}])

    assert PORTABILIDADE in jornada.ultima_saida()
    assert OFERTA_C6 not in jornada.ultima_saida()


# ------------------------------- a oferta vigente que o painel confere (issue 32)

REAIS = re.compile(r"R\$ ([\d.]+)(?:,(\d{2}))?")


def _reais_da_ultima_fala(jornada: Jornada) -> set[Decimal]:
    achados = REAIS.findall(jornada.ultima_saida())
    return {
        Decimal(f"{inteiro.replace('.', '')}.{centavos or '00'}") for inteiro, centavos in achados
    }


def _vigente(jornada: Jornada) -> Oferta | None:
    with abrir_sessao(jornada.fabrica) as sessao:
        chaves = sessao.scalars(
            select(Mensagem.chave_mensagem)
            .where(Mensagem.direcao == "saida", Mensagem.chave_mensagem.is_not(None))
            .order_by(Mensagem.id.desc())
        ).all()
        aceito = bool(
            sessao.scalar(select(Consentimento.id).where(Consentimento.tipo == "icred_aceite"))
        )
    ofertas = ofertas_da_conversa(
        jornada.servico.jornada(jornada.id), [c for c in chaves if c], aceito
    )
    return next((o for o in ofertas if o.vigente), None)


def test_oferta_vigente_sai_do_contrato_novo_para_o_icred_quando_ele_e_mostrado(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    assert _vigente(jornada) is None

    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    vigente = _vigente(jornada)
    assert vigente is not None and vigente.ramo == "contrato_novo"
    # Os valores conferidos são os reais que o cliente leu na oferta.
    assert set(vigente.valores) == _reais_da_ultima_fala(jornada)

    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    jornada.falar("esse não quero")
    jornada.falar("sim")
    # Pedido de SIM e aviso de consulta não são oferta: a recusada segue a última mostrada.
    vigente = _vigente(jornada)
    assert vigente is not None and vigente.ramo == "contrato_novo"

    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    vigente = _vigente(jornada)
    assert vigente is not None and vigente.ramo == "icred"
    assert set(vigente.valores) == _reais_da_ultima_fala(jornada)


def test_oferta_vigente_e_a_portabilidade_quando_o_icred_nao_ganha(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)
    troco = jornada.estado()["portability_result"]["troco_total"]
    jornada.falar("sim")

    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": float(troco)}])

    assert PORTABILIDADE in jornada.ultima_saida()
    vigente = _vigente(jornada)
    assert vigente is not None and vigente.ramo == "portabilidade"
    assert set(vigente.valores) == _reais_da_ultima_fala(jornada)
    assert not vigente.recusada

    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    jornada.falar("não quero")
    vigente = _vigente(jornada)
    assert vigente is not None and (vigente.ramo, vigente.recusada) == ("portabilidade", True)


def test_oferta_recusada_segue_vigente_e_marcada_ate_a_proxima_oferta(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)
    vigente = _vigente(jornada)
    assert vigente is not None and (vigente.ramo, vigente.recusada) == ("contrato_novo", True)

    jornada.falar("sim")
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    vigente = _vigente(jornada)
    assert vigente is not None and (vigente.ramo, vigente.recusada) == ("icred", False)

    jornada.falar("não")
    # O NÃO ao iCred devolve a conversa à portabilidade, que passa a ser a vigente.
    vigente = _vigente(jornada)
    assert vigente is not None and (vigente.ramo, vigente.recusada) == ("portabilidade", False)


def test_pacote_do_icred_aceito_nao_sai_como_recusado(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _ate_a_recusa_do_contrato_novo(jornada, fakes)
    jornada.falar("sim")
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])

    assert jornada.falar("sim").handoff_reason == "icred_aceite"

    assert jornada.estado()["icred"]["etapa"] == "fim"
    vigente = _vigente(jornada)
    assert vigente is not None and (vigente.ramo, vigente.recusada) == ("icred", False)


# ------------------------------- o SIM vale só para o último pedido mostrado

OUTRO_TITULAR = "52998224725"
PROVA_C6 = ("simulacao_c6", "2026-11-16", CONSENTIMENTO_C6)
PROVA_ICRED_DEPOIS = ("icred_consulta", "icred-1-depois-c6", PEDIDO_DEPOIS_DO_C6)


def test_extrato_novo_cancela_o_pedido_do_icred_e_o_sim_vai_para_o_c6(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    completo = dict(fakes.llm.extrato)
    fakes.llm.extrato = {**completo, "numeroBeneficio": None, "baseCalculo": None}
    assert _um_pedido_de_sim(jornada.extrato().answer) == PEDIDO_ORIGINAL
    fakes.llm.extrato = completo
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    # O último pedido mostrado é o do C6: o SIM simula no C6 e mais nada.
    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    assert _provas(jornada) == [PROVA_C6]
    assert simulador_icred.CHAMADAS == []

    # O iCred pergunta de novo na vez dele, já com a abertura de depois do C6.
    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    assert _um_pedido_de_sim(jornada.falar("esse não quero").answer) == PEDIDO_DEPOIS_DO_C6
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada) == [PROVA_C6, PROVA_ICRED_DEPOIS]


def test_extrato_de_outro_titular_cancela_o_pedido_do_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    assert _um_pedido_de_sim(jornada.falar("não").answer) == PEDIDO_DEPOIS_DO_C6
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_TITULAR}
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    assert _provas(jornada) == [PROVA_C6]
    assert simulador_icred.CHAMADAS == []

    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    assert _um_pedido_de_sim(jornada.falar("esse não quero").answer) == PEDIDO_DEPOIS_DO_C6
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada) == [PROVA_C6, PROVA_ICRED_DEPOIS]
    # A consulta sai com o CPF do extrato que vale agora.
    (remota,) = simulador_icred.CONSULTAS.values()
    assert remota["cpf"] == OUTRO_TITULAR


def _icred_consultando_e_o_c6_sem_pedir(jornada: Jornada, fakes: Fakes) -> None:
    """O iCred consulta sem o C6 ter pedido o SIM; o extrato completo fica pronto.

    O extrato completo do mesmo titular, mandado depois, faz o C6 pedir o SIM.
    """

    completo = dict(fakes.llm.extrato)
    fakes.llm.extrato = {**completo, "numeroBeneficio": None, "baseCalculo": None}
    assert _um_pedido_de_sim(jornada.extrato().answer) == PEDIDO_ORIGINAL
    assert jornada.falar("sim").answer == textos.PEDIR_CPF
    assert jornada.falar(CPF).answer == textos.CONSULTANDO
    fakes.llm.extrato = completo


def test_extrato_novo_suspende_a_oferta_do_icred_ate_ela_ser_mostrada_de_novo(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _icred_consultando_e_o_c6_sem_pedir(jornada, fakes)
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta_icred = jornada.ultima_saida()
    assert oferta_icred.startswith("Consultei o iCred")
    # O mesmo titular manda o extrato completo: agora o C6 pede o SIM dele.
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    # O SIM responde ao C6, não à oferta do iCred que ficou para trás.
    resposta = jornada.falar("sim")

    assert OFERTA_C6 in (resposta.answer or "")
    assert [tipo for tipo, _versao, _texto in _provas(jornada)] == [
        "icred_consulta",
        "simulacao_c6",
    ]
    # Recusado o contrato novo, a oferta do iCred volta e só então pode ser aceita.
    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    assert jornada.falar("esse não quero").answer == oferta_icred
    aceite = jornada.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert jornada.provas()[-1] == ("icred_aceite", CPF, "sim")


def test_pedido_do_c6_aberto_nao_ganha_prova_pelo_sim_dado_a_oferta_do_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType, simulador_c6: ModuleType
) -> None:
    _icred_consultando_e_o_c6_sem_pedir(jornada, fakes)
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    assert jornada.ultima_saida().startswith("Consultei o iCred")

    # O último pedido mostrado é a oferta do iCred: o SIM é o aceite dela.
    aceite = jornada.falar("sim")

    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert [tipo for tipo, _versao, _texto in _provas(jornada)] == [
        "icred_consulta",
        "icred_aceite",
    ]
    assert ("POST", ROTA_SIMULACAO) not in simulador_c6.CHAMADAS


def test_duvida_na_oferta_do_icred_nao_refaz_o_pedido_do_c6_que_ficou_aberto(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    _icred_consultando_e_o_c6_sem_pedir(jornada, fakes)
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta_icred = jornada.ultima_saida()

    # A dúvida é respondida e só a oferta do iCred, a última mostrada, volta
    # no mesmo turno; o pedido do C6 que ficou para trás não.
    assert jornada.falar("tem seguro?").answer == f"{RESPOSTA_DA_DUVIDA}\n\n{oferta_icred}"

    aceite = jornada.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert [tipo for tipo, _versao, _texto in _provas(jornada)] == [
        "icred_consulta",
        "icred_aceite",
    ]


def test_duvida_no_pedido_do_icred_depois_do_c6_traz_o_pedido_de_volta(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    assert _um_pedido_de_sim(jornada.falar("não").answer) == PEDIDO_DEPOIS_DO_C6

    # A versão reenviada é a que foi mostrada, e é ela que vai para a prova.
    resposta = jornada.falar("tem seguro?").answer
    assert resposta == f"{RESPOSTA_DA_DUVIDA}\n\n{PEDIDO_DEPOIS_DO_C6}"
    assert simulador_icred.CHAMADAS == []

    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada) == [PROVA_ICRED_DEPOIS]


def test_duvida_no_pedido_de_cpf_do_icred_com_o_c6_ligado_traz_o_pedido_de_volta(
    jornada: Jornada, fakes: Fakes
) -> None:
    # Sem número do benefício o C6 não pede o SIM nem o CPF: o iCred pede.
    fakes.llm.extrato = {**fakes.llm.extrato, "numeroBeneficio": None, "baseCalculo": None}
    assert _um_pedido_de_sim(jornada.extrato().answer) == PEDIDO_ORIGINAL
    assert jornada.falar("sim").answer == textos.PEDIR_CPF

    resposta = jornada.falar("para que serve?").answer
    assert resposta == f"{RESPOSTA_DA_DUVIDA}\n\n{textos.PEDIR_CPF}"
    assert _provas(jornada) == []

    assert jornada.falar(CPF).answer == textos.CONSULTANDO
    assert _provas(jornada) == [("icred_consulta", "icred-1", PEDIDO_ORIGINAL)]


def test_duvida_depois_de_extrato_recusado_nao_traz_o_pedido_de_volta(
    jornada: Jornada, fakes: Fakes
) -> None:
    jornada.extrato()
    assert _um_pedido_de_sim(jornada.falar("não").answer) == PEDIDO_DEPOIS_DO_C6
    _extrato_recusado(jornada, fakes)

    # O pedido não era a última mensagem antes da dúvida: só a resposta sai, e
    # o SIM seguinte refaz o pedido.
    assert jornada.falar("tem seguro?").answer == RESPOSTA_DA_DUVIDA
    assert _um_pedido_de_sim(jornada.falar("sim").answer) == PEDIDO_DEPOIS_DO_C6
    assert _provas(jornada) == []


def test_so_com_o_icred_o_extrato_reenviado_refaz_a_pergunta_e_o_sim_seguinte_vale(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> None:
    fakes.llm.extrato = dados_extrato()
    jornada = Jornada(fabrica, http_icred, fakes, simulador_icred)
    assert jornada.extrato().answer == PEDIDO_ORIGINAL
    assert jornada.falar("sim").answer == textos.PEDIR_CPF

    # Extrato de novo depois do SIM e antes do CPF: a pergunta volta ao começo.
    assert jornada.extrato().answer == PEDIDO_ORIGINAL
    assert _provas(jornada) == []

    assert jornada.falar("sim, autorizo").answer == textos.PEDIR_CPF
    assert jornada.falar(CPF).answer == textos.CONSULTANDO
    assert _provas(jornada) == [("icred_consulta", "icred-1", PEDIDO_ORIGINAL)]


# ------------------------------------------- extrato de outro titular: descarta


def _ofertas_do_icred_enviadas(jornada: Jornada) -> int:
    with abrir_sessao(jornada.fabrica) as sessao:
        return int(
            sessao.scalar(
                select(func.count())
                .select_from(Mensagem)
                .where(Mensagem.direcao == "saida", Mensagem.conteudo.like("Consultei o iCred%"))
            )
            or 0
        )


def _c6_recusado_ate_o_pedido_do_icred(jornada: Jornada, fakes: Fakes) -> None:
    """SIM ao C6, contrato novo recusado e o pedido do iCred na vez dele."""

    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    fakes.jev.resultado = resultado_jev(resposta_oferta="recusa")
    assert _um_pedido_de_sim(jornada.falar("esse não quero").answer) == PEDIDO_DEPOIS_DO_C6


def test_extrato_de_outro_titular_descarta_a_oferta_do_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("não")
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    assert jornada.ultima_saida().startswith("Consultei o iCred")
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_TITULAR}
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6

    # A oferta era do titular anterior: não volta; o iCred pergunta de novo.
    _c6_recusado_ate_o_pedido_do_icred(jornada, fakes)
    assert jornada.falar("sim").answer == textos.CONSULTANDO

    assert _ofertas_do_icred_enviadas(jornada) == 1
    assert jornada.provas() == [
        ("icred_consulta", CPF, "sim"),
        ("simulacao_c6", OUTRO_TITULAR, "sim"),
        ("icred_consulta", OUTRO_TITULAR, "sim"),
    ]
    assert [c["cpf"] for c in simulador_icred.CONSULTAS.values()] == [CPF, OUTRO_TITULAR]


def test_resultado_da_consulta_do_titular_anterior_nao_chega_ao_cliente(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("não")
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    (antiga,) = simulador_icred.CONSULTAS
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_TITULAR}
    assert _um_pedido_de_sim(jornada.extrato().answer) == CONSENTIMENTO_C6
    produtos = [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}]

    # O resultado da consulta do titular anterior chega: ninguém recebe nada.
    orfao = simulador_icred.concluir(antiga, "COM_OFERTA", produtos)
    job.aplicar(jornada.fabrica, orfao, jornada.servico)

    assert jornada.ultima_saida() == CONSENTIMENTO_C6
    assert _ofertas_do_icred_enviadas(jornada) == 0
    # A linha fica como histórico, fora das consultas abertas.
    with abrir_sessao(jornada.fabrica) as sessao:
        assert sessao.scalars(select(ConsultaIcred.estado)).all() == ["desistida"]

    # O novo titular tem o pedido e a consulta dele; o resultado antigo repetido
    # com a consulta nova aberta também não vira oferta, e o prazo atrasado da
    # consulta antiga não faz a conversa desistir da nova.
    _c6_recusado_ate_o_pedido_do_icred(jornada, fakes)
    assert jornada.falar("sim").answer == textos.CONSULTANDO
    job.aplicar(jornada.fabrica, orfao, jornada.servico)
    jornada.servico.continuar(jornada.id, job.EVENTO_PRAZO)
    assert _ofertas_do_icred_enviadas(jornada) == 0
    assert jornada.ultima_saida() == textos.CONSULTANDO
    assert jornada.estado()["icred"]["etapa"] == "consultando"

    nova = next(c for c in simulador_icred.CONSULTAS if c != antiga)
    job.aplicar(
        jornada.fabrica, simulador_icred.concluir(nova, "COM_OFERTA", produtos), jornada.servico
    )
    assert jornada.ultima_saida().startswith("Consultei o iCred")
    aceite = jornada.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert jornada.provas()[-1] == ("icred_aceite", OUTRO_TITULAR, "sim")


def test_extrato_de_outro_titular_que_vai_para_o_atendente_tambem_descarta_a_oferta(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("não")
    jornada.falar("sim")
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    # Espécie que o C6 não atende: o extrato termina em handoff dentro da leitura.
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_TITULAR, "especie": "87"}
    assert jornada.extrato().status == "handoff"

    # Devolvida à IA, a conversa não tem mais oferta do iCred para aceitar.
    jornada.servico.liberar(jornada.id)
    resposta = jornada.falar("sim")

    assert resposta.handoff_reason != "icred_aceite"
    assert [tipo for tipo, _cpf, _resposta in jornada.provas()] == ["icred_consulta"]
    assert _ofertas_do_icred_enviadas(jornada) == 1


def test_so_com_o_icred_o_extrato_de_outro_titular_descarta_a_oferta(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> None:
    fakes.llm.extrato = {**dados_extrato(), "cpf": CPF}
    jornada = Jornada(fabrica, http_icred, fakes, simulador_icred)
    jornada.ate_a_consulta()
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_TITULAR}

    # Sem o C6 a `porta` roda no mesmo turno: sai o pedido, não a oferta antiga.
    assert jornada.extrato().answer == PEDIDO_ORIGINAL

    assert jornada.falar("sim").answer == textos.PEDIR_CPF
    assert [tipo for tipo, _cpf, _resposta in jornada.provas()] == ["icred_consulta"]
    assert _ofertas_do_icred_enviadas(jornada) == 1


# ------------------------------ a última mensagem do agente não foi o pedido


@pytest.fixture
def so_icred(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    fakes.llm.extrato = dados_extrato()
    return Jornada(fabrica, http_icred, fakes, simulador_icred)


def _extrato_recusado(jornada: Jornada, fakes: Fakes) -> None:
    fakes.llm.erro = RuntimeError("ilegível")
    assert jornada.extrato().answer == MENSAGEM_EXTRATO_ILEGIVEL
    fakes.llm.erro = None


def test_sim_depois_de_extrato_recusado_refaz_o_pedido_do_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    assert _um_pedido_de_sim(jornada.falar("não").answer) == PEDIDO_DEPOIS_DO_C6
    _extrato_recusado(jornada, fakes)

    # A última mensagem foi a recusa do extrato: o SIM não é resposta ao pedido.
    assert _um_pedido_de_sim(jornada.falar("sim").answer) == PEDIDO_DEPOIS_DO_C6
    assert _provas(jornada) == []
    assert simulador_icred.CHAMADAS == []

    assert jornada.falar("sim").answer == textos.CONSULTANDO
    assert _provas(jornada) == [PROVA_ICRED_DEPOIS]


def test_sim_depois_de_extrato_recusado_refaz_a_oferta_do_icred(
    jornada: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("não")
    jornada.falar("sim")
    jornada.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta_icred = jornada.ultima_saida()
    _extrato_recusado(jornada, fakes)

    assert jornada.falar("sim").answer == oferta_icred
    assert [tipo for tipo, _cpf, _resposta in jornada.provas()] == ["icred_consulta"]

    aceite = jornada.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert jornada.provas()[-1] == ("icred_aceite", CPF, "sim")


def test_so_com_o_icred_o_sim_depois_de_extrato_recusado_refaz_o_pedido(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    assert so_icred.extrato().answer == PEDIDO_ORIGINAL
    _extrato_recusado(so_icred, fakes)

    assert so_icred.falar("sim").answer == PEDIDO_ORIGINAL
    assert so_icred.falar("sim").answer == textos.PEDIR_CPF
    # O CPF só é lido como resposta ao pedido dele: com uma mensagem vazia no
    # meio, o pedido do CPF é refeito e o SIM já dado continua valendo.
    assert so_icred.falar("").answer == MENSAGEM_SEM_TEXTO
    assert so_icred.falar(CPF).answer == textos.PEDIR_CPF
    # Nem um CPF inválido é lido: sai o pedido, não o aviso de CPF inválido.
    assert so_icred.falar("").answer == MENSAGEM_SEM_TEXTO
    assert so_icred.falar("123").answer == textos.PEDIR_CPF
    assert _provas(so_icred) == []
    assert simulador_icred.CHAMADAS == []

    assert so_icred.falar(CPF).answer == textos.CONSULTANDO
    assert _provas(so_icred) == [("icred_consulta", "icred-1", PEDIDO_ORIGINAL)]


def test_so_com_o_icred_o_sim_depois_de_extrato_recusado_refaz_a_oferta(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    so_icred.ate_a_consulta()
    so_icred.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta_icred = so_icred.ultima_saida()
    _extrato_recusado(so_icred, fakes)

    assert so_icred.falar("sim").answer == oferta_icred
    assert [tipo for tipo, _cpf, _resposta in so_icred.provas()] == ["icred_consulta"]

    aceite = so_icred.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
