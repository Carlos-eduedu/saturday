"""Pontas do consentimento que sobraram do C6 com o iCred (issue 42).

CPF digitado diferente do extrato, atendente no meio de um pedido ou de uma
oferta, a etapa do CPF sem pergunta e os casos menores. Postgres real e os
simuladores em processo; o atendente entra e sai pelos verbos do atendimento.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import ModuleType

import pytest
from conftest import Fakes, resultado_jev, settings_icred
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from test_clt_devolucao import assumir_e_desfazer
from test_icred import CPF, RESPOSTA_DA_DUVIDA, Jornada
from test_portabilidade_fluxo import dados_extrato

from saturday.agent.icred import textos
from saturday.agent.textos import CONSENTIMENTO_C6, MENSAGEM_BOAS_VINDAS
from saturday.bancos.c6.cliente import ROTA_SIMULACAO, ClienteC6
from saturday.bancos.icred.cliente import ABERTAS, DESISTIDA
from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import ConsultaIcred, Conversa, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

OUTRO_CPF = "52998224725"
# Por extenso: o cliente não pode ver nenhum dos dois CPFs nesta fala.
CPF_NAO_CONFERE = (
    "Esse CPF não confere com o do extrato que você enviou. Envie o CPF do "
    "titular do extrato, só os números, por favor."
)
PEDIDO_DEPOIS_DO_C6 = textos.PEDIR_SIM_DEPOIS_C6
OFERTA_C6 = "contrato novo disponível"
LIBERACOES = ["devolver", "liberar", "prazo"]


def _extrato_c6() -> dict[str, object]:
    return {**dados_extrato(), "cpf": CPF, "numeroBeneficio": "1234567890", "baseCalculo": 1518.0}


@pytest.fixture
def so_icred(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    """Só o iCred ligado, com o CPF legível no extrato."""

    fakes.llm.extrato = {**dados_extrato(), "cpf": CPF}
    return Jornada(fabrica, http_icred, fakes, simulador_icred)


def _com_c6(jornada: Jornada, http_c6: TestClient, *, icred: bool) -> Jornada:
    settings = Settings(
        environment="pytest",
        c6_ativo=True,
        c6_base_url="http://c6",
        c6_usuario="usuario-do-simulador",
        c6_senha=SecretStr("senha-do-simulador"),
        c6_codigo_promotora="000001",
    )
    c6 = ClienteC6(http_c6, settings, jornada.fabrica, dormir=lambda _: None)
    contexto = replace(jornada.servico.context, c6_ativo=True, c6=c6)
    jornada.servico.context = contexto if icred else replace(contexto, icred=None)
    return jornada


@pytest.fixture
def os_dois(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    http_c6: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    fakes.llm.extrato = _extrato_c6()
    return _com_c6(Jornada(fabrica, http_icred, fakes, simulador_icred), http_c6, icred=True)


@pytest.fixture
def so_c6(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    http_c6: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    fakes.llm.extrato = _extrato_c6()
    return _com_c6(Jornada(fabrica, http_icred, fakes, simulador_icred), http_c6, icred=False)


def _tipos_de_prova(jornada: Jornada) -> list[str]:
    return [tipo for tipo, _cpf, _resposta in jornada.provas()]


def _atendente_no_meio(jornada: Jornada, liberacao: str) -> None:
    """Um atendente assume a conversa, e ela volta à IA por um dos três caminhos.

    O que ele escreve pelo painel não entra no grafo: aqui basta a entrada e a
    saída dele. No `prazo`, quem devolve é o próprio turno seguinte do cliente.
    """

    with abrir_sessao(jornada.fabrica) as sessao:
        usuario = UsuarioPainel(
            email=f"{liberacao}@exemplo.test", nome="Ana", senha_hash="x", perfil="atendente"
        )
        sessao.add(usuario)
        sessao.flush()
        conversa = repositorios.buscar_conversa(sessao, jornada.id)
        assert conversa is not None
        atendimento.assumir(sessao, conversa, usuario.id)
        ids = conversa.id, usuario.id
    if liberacao == "devolver":
        jornada.servico.devolver(*ids, gestor=False)
    elif liberacao == "liberar":
        jornada.servico.liberar(jornada.id)
    else:
        jornada.servico.settings = settings_icred(handoff_auto_release_horas=1)
        with abrir_sessao(jornada.fabrica) as sessao:
            sessao.execute(
                update(Conversa)
                .where(Conversa.conversation_id == jornada.id)
                .values(atendimento="handoff", atendimento_em=func.now() - timedelta(hours=2))
            )


# ------------------------------------------- A. CPF digitado diferente do extrato


def test_cpf_diferente_do_extrato_nao_consulta_e_pede_de_novo(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    assert so_icred.falar("sim").answer == textos.PEDIR_CPF

    resposta = so_icred.falar(OUTRO_CPF)

    assert resposta.answer == CPF_NAO_CONFERE
    assert not any(c.isdigit() for c in resposta.answer or "")
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []

    # O aviso é um pedido de CPF: o CPF do extrato, logo depois, é lido.
    assert so_icred.falar(CPF).answer == textos.CONSULTANDO
    assert so_icred.provas() == [("icred_consulta", CPF, "sim")]


def test_cpf_diferente_do_extrato_pela_segunda_vez_vai_para_o_atendente(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")
    assert so_icred.falar(OUTRO_CPF).answer == CPF_NAO_CONFERE

    resposta = so_icred.falar(OUTRO_CPF)

    assert (resposta.status, resposta.handoff_reason) == ("handoff", "icred_cpf_divergente")
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []


def test_cpf_invalido_e_cpf_que_nao_confere_sao_contados_separados(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")

    # Um erro de cada tipo não soma dois: cada um ainda está na primeira vez.
    assert so_icred.falar("123").answer == textos.CPF_INVALIDO
    assert so_icred.falar(OUTRO_CPF).answer == CPF_NAO_CONFERE
    assert simulador_icred.CHAMADAS == []

    # O segundo de formato segue sem o iCred, como antes; não vira handoff.
    resposta = so_icred.falar("123")
    assert (resposta.answer or "").startswith("Analisei o seu extrato.")
    assert resposta.handoff_reason != "icred_cpf_divergente"
    assert so_icred.provas() == []


def test_extrato_sem_cpf_legivel_aceita_o_cpf_digitado(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    fakes.llm.extrato = dados_extrato()
    so_icred.extrato()
    so_icred.falar("sim")

    assert so_icred.falar(OUTRO_CPF).answer == textos.CONSULTANDO
    assert so_icred.provas() == [("icred_consulta", OUTRO_CPF, "sim")]


def test_cpf_que_a_conversa_ja_tem_e_nao_e_o_do_extrato_nao_e_consultado(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    cliente = {**so_icred.estado()["cliente"], "cpf": OUTRO_CPF}
    so_icred.servico.graph.update_state(so_icred.servico.config(so_icred.id), {"cliente": cliente})

    assert so_icred.falar("sim").answer == textos.PEDIR_CPF
    assert simulador_icred.CHAMADAS == []
    assert so_icred.provas() == []


def test_mesmo_extrato_reenviado_depois_do_cpf_errado_nao_conta_como_outro_titular(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")
    so_icred.falar(OUTRO_CPF)
    assert so_icred.falar(CPF).answer == textos.CONSULTANDO

    # O titular da conversa continua sendo o do extrato: a consulta dele fica.
    assert so_icred.extrato().answer == textos.CONSULTANDO

    with abrir_sessao(so_icred.fabrica) as sessao:
        (linha,) = sessao.scalars(select(ConsultaIcred)).all()
        assert linha.estado in ABERTAS
    assert len(simulador_icred.CONSULTAS) == 1


# ------------------------------------------------------ B. atendente no meio


@pytest.mark.parametrize("liberacao", LIBERACOES)
def test_so_icred_sim_depois_do_atendente_refaz_o_pedido(
    so_icred: Jornada, simulador_icred: ModuleType, liberacao: str
) -> None:
    assert so_icred.extrato().answer == textos.PEDIR_SIM
    _atendente_no_meio(so_icred, liberacao)

    # O cliente conversou com o atendente depois do pedido: o SIM não é dele.
    assert so_icred.falar("sim").answer == textos.PEDIR_SIM
    assert so_icred.provas() == []

    assert so_icred.falar("sim").answer == textos.PEDIR_CPF
    assert so_icred.falar(CPF).answer == textos.CONSULTANDO
    assert so_icred.provas() == [("icred_consulta", CPF, "sim")]


def test_so_icred_cpf_depois_do_atendente_refaz_o_pedido_do_cpf(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    assert so_icred.falar("sim").answer == textos.PEDIR_CPF
    _atendente_no_meio(so_icred, "devolver")

    assert so_icred.falar(CPF).answer == textos.PEDIR_CPF
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []

    assert so_icred.falar(CPF).answer == textos.CONSULTANDO


@pytest.mark.parametrize("liberacao", LIBERACOES)
def test_so_icred_sim_depois_do_atendente_refaz_a_oferta(
    so_icred: Jornada, simulador_icred: ModuleType, liberacao: str
) -> None:
    so_icred.ate_a_consulta()
    so_icred.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta = so_icred.ultima_saida()
    _atendente_no_meio(so_icred, liberacao)

    resposta = so_icred.falar("sim")

    assert (resposta.status, resposta.answer) == ("answered", oferta)
    assert _tipos_de_prova(so_icred) == ["icred_consulta"]

    aceite = so_icred.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert so_icred.provas()[-1] == ("icred_aceite", CPF, "sim")


def test_so_icred_sim_depois_de_o_atendente_escrever_e_desfazer_refaz_o_pedido(
    so_icred: Jornada, simulador_icred: ModuleType
) -> None:
    assert so_icred.extrato().answer == textos.PEDIR_SIM
    assumir_e_desfazer(so_icred.servico, so_icred.fabrica, so_icred.id, escreve=True)

    # O "Desfazer" depois de o atendente escrever conta como atendimento (decisão 0033).
    assert so_icred.falar("sim").answer == textos.PEDIR_SIM
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []

    assert so_icred.falar("sim").answer == textos.PEDIR_CPF


def test_so_icred_sim_depois_de_desfazer_sem_o_atendente_escrever_vale(
    so_icred: Jornada,
) -> None:
    assert so_icred.extrato().answer == textos.PEDIR_SIM
    assumir_e_desfazer(so_icred.servico, so_icred.fabrica, so_icred.id, escreve=False)

    assert so_icred.falar("sim").answer == textos.PEDIR_CPF


def test_duvida_depois_do_atendente_nao_traz_o_pedido_e_o_sim_seguinte_refaz(
    so_icred: Jornada,
) -> None:
    so_icred.extrato()
    _atendente_no_meio(so_icred, "devolver")

    # O pedido não era mais a última coisa que o cliente viu: só a resposta.
    assert so_icred.falar("como funciona?").answer == RESPOSTA_DA_DUVIDA
    assert so_icred.falar("sim").answer == textos.PEDIR_SIM
    assert so_icred.provas() == []


def test_os_dois_sim_depois_do_atendente_refaz_o_pedido_do_icred(
    os_dois: Jornada, simulador_icred: ModuleType
) -> None:
    assert os_dois.extrato().answer == CONSENTIMENTO_C6
    assert os_dois.falar("não").answer == PEDIDO_DEPOIS_DO_C6
    _atendente_no_meio(os_dois, "devolver")

    assert os_dois.falar("sim").answer == PEDIDO_DEPOIS_DO_C6
    assert os_dois.provas() == []
    assert simulador_icred.CHAMADAS == []

    assert os_dois.falar("sim").answer == textos.CONSULTANDO
    assert _tipos_de_prova(os_dois) == ["icred_consulta"]


def test_os_dois_sim_depois_do_atendente_refaz_a_oferta_do_icred(
    os_dois: Jornada, simulador_icred: ModuleType
) -> None:
    os_dois.extrato()
    os_dois.falar("não")
    os_dois.falar("sim")
    os_dois.resultado("COM_OFERTA", [{**simulador_icred.PRODUTO_NOVO, "liberado": 50000.0}])
    oferta = os_dois.ultima_saida()
    _atendente_no_meio(os_dois, "devolver")

    assert os_dois.falar("sim").answer == oferta
    assert _tipos_de_prova(os_dois) == ["icred_consulta"]

    aceite = os_dois.falar("sim")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")


# No C6 a devolução já apaga o pedido e a oferta do estado (`aguardando` e
# `oferta_pendente`): o SIM de depois não tem o que aceitar. Estes testes só
# mostram que o caso não existe; nenhum mecanismo novo é do C6.
@pytest.mark.parametrize("bancos", ["os_dois", "so_c6"])
@pytest.mark.parametrize("liberacao", LIBERACOES)
def test_sim_depois_do_atendente_nao_autoriza_a_simulacao_do_c6(
    request: pytest.FixtureRequest, simulador_c6: ModuleType, bancos: str, liberacao: str
) -> None:
    jornada: Jornada = request.getfixturevalue(bancos)
    assert jornada.extrato().answer == CONSENTIMENTO_C6
    _atendente_no_meio(jornada, liberacao)

    resposta = jornada.falar("sim")

    assert resposta.answer == RESPOSTA_DA_DUVIDA
    assert jornada.provas() == []
    assert ("POST", ROTA_SIMULACAO) not in simulador_c6.CHAMADAS
    assert "c6_autorizado" not in jornada.estado()["cliente"]


@pytest.mark.parametrize("bancos", ["os_dois", "so_c6"])
@pytest.mark.parametrize("liberacao", LIBERACOES)
def test_sim_depois_do_atendente_nao_aceita_o_contrato_novo_do_c6(
    request: pytest.FixtureRequest, fakes: Fakes, bancos: str, liberacao: str
) -> None:
    jornada: Jornada = request.getfixturevalue(bancos)
    jornada.extrato()
    assert OFERTA_C6 in (jornada.falar("sim").answer or "")
    _atendente_no_meio(jornada, liberacao)
    # Mesmo que o classificador leia um aceite.
    fakes.jev.resultado = resultado_jev(resposta_oferta="aceita")

    resposta = jornada.falar("sim")

    assert (resposta.status, resposta.answer) == ("answered", RESPOSTA_DA_DUVIDA)
    assert resposta.handoff_reason != "aceitou_contrato_novo"
    assert jornada.estado()["c6_novo"]["situacao"] == "ofertado"
    assert _tipos_de_prova(jornada) == ["simulacao_c6"]


# A portabilidade pura segue o C6: a devolução zera `oferta_pendente` (issue 44,
# só a confirmação; nada mudou aqui).
def test_sim_depois_do_atendente_nao_aceita_a_portabilidade(
    so_icred: Jornada, fakes: Fakes
) -> None:
    so_icred.servico.context = replace(so_icred.servico.context, icred=None)
    assert (so_icred.extrato().answer or "").startswith("Analisei o seu extrato.")
    assert so_icred.estado()["oferta_pendente"] is True
    _atendente_no_meio(so_icred, "devolver")
    # Mesmo que o classificador leia um aceite.
    fakes.jev.resultado = resultado_jev(resposta_oferta="aceita", resposta_conf=0.9)

    resposta = so_icred.falar("sim")

    assert (resposta.status, resposta.answer) == ("answered", RESPOSTA_DA_DUVIDA)
    assert resposta.handoff_reason != "aceitou_portabilidade"
    assert so_icred.provas() == []


# ------------------------- C. etapa do CPF: afirmação curta não vai à triagem


@pytest.mark.parametrize(
    "mensagem", ["ok", "sim", "tá bom", "Tá bom!", "OK, certo.", "beleza", "aceito"]
)
def test_no_pedido_de_cpf_a_afirmacao_curta_recebe_o_pedido_de_novo_sem_modelo(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType, mensagem: str
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")
    classificadas = len(fakes.jev.chamadas)

    assert so_icred.falar(mensagem).answer == textos.PEDIR_CPF

    assert len(fakes.jev.chamadas) == classificadas
    assert fakes.llm.chamadas_responder == []
    # Não conta como CPF errado: o primeiro erro de formato ainda só avisa.
    assert so_icred.falar("123").answer == textos.CPF_INVALIDO
    assert so_icred.falar(CPF).answer == textos.CONSULTANDO
    assert so_icred.provas() == [("icred_consulta", CPF, "sim")]


@pytest.mark.parametrize(
    "mensagem",
    ["para que serve", "para que serve?", "não", "sim, mas por quê", "ok mas não quero", "certo?"],
)
def test_no_pedido_de_cpf_o_resto_vai_para_a_triagem_e_o_pedido_volta(
    so_icred: Jornada, fakes: Fakes, mensagem: str
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")

    resposta = so_icred.falar(mensagem)

    assert resposta.answer == f"{RESPOSTA_DA_DUVIDA}\n\n{textos.PEDIR_CPF}"
    assert fakes.jev.chamadas[-1][0] == mensagem
    assert len(fakes.llm.chamadas_responder) == 1
    # Não conta como CPF errado, e o SIM já dado continua valendo.
    assert so_icred.falar("123").answer == textos.CPF_INVALIDO
    assert so_icred.falar(CPF).answer == textos.CONSULTANDO


def test_no_pedido_de_cpf_quem_pede_um_atendente_vai_para_o_atendente(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    so_icred.falar("sim")
    fakes.jev.resultado = resultado_jev(intent="humano")

    resposta = so_icred.falar("quero falar com um atendente")

    assert (resposta.status, resposta.handoff_reason) == ("handoff", "pediu_humano")
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []


# ------------------------------------------------------------------ E. menores


def test_sim_depois_do_cumprimento_refaz_o_pedido_e_nao_grava_prova(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    assert so_icred.extrato().answer == textos.PEDIR_SIM
    fakes.jev.resultado = resultado_jev(intent="saudacao")
    # A saudação fixa só sai sem extrato no estado, como a retenção o deixa.
    so_icred.servico.graph.update_state(so_icred.servico.config(so_icred.id), {"hiscon": None})

    # O cumprimento recebe a saudação sem o pedido (fica como está).
    assert so_icred.falar("oi").answer == MENSAGEM_BOAS_VINDAS

    assert so_icred.falar("sim").answer == textos.PEDIR_SIM
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []


def test_cumprimento_com_o_extrato_no_estado_e_tratado_como_duvida(
    so_icred: Jornada, fakes: Fakes
) -> None:
    so_icred.extrato()
    fakes.jev.resultado = resultado_jev(intent="saudacao")

    # Com jornada em curso o cumprimento é dúvida: resposta e o pedido de volta.
    assert so_icred.falar("oi").answer == f"{RESPOSTA_DA_DUVIDA}\n\n{textos.PEDIR_SIM}"
    assert so_icred.provas() == []


def test_segunda_duvida_no_pedido_de_sim_abandona_o_icred_sem_responder(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    so_icred.extrato()
    assert so_icred.falar("como funciona?").answer == f"{RESPOSTA_DA_DUVIDA}\n\n{textos.PEDIR_SIM}"

    resposta = so_icred.falar("e demora?")

    # A segunda dúvida não é respondida: sai o resultado do extrato.
    assert (resposta.answer or "").startswith("Analisei o seu extrato.")
    assert len(fakes.llm.chamadas_responder) == 1
    assert so_icred.estado()["icred"]["etapa"] == "fim"
    assert so_icred.provas() == []
    assert simulador_icred.CHAMADAS == []


def test_extrato_que_nao_conferiu_nao_descarta_a_consulta_pelo_cpf_lido(
    so_icred: Jornada, fakes: Fakes, simulador_icred: ModuleType
) -> None:
    so_icred.ate_a_consulta()
    # A soma das parcelas não fecha com a margem: a leitura não é confiável,
    # e o CPF lido dela também não.
    fakes.llm.extrato = {**fakes.llm.extrato, "cpf": OUTRO_CPF, "margemUtilizada": 9999.0}

    resposta = so_icred.extrato()

    assert (resposta.status, resposta.handoff_reason) == ("handoff", "hiscon_nao_conferiu")
    with abrir_sessao(so_icred.fabrica) as sessao:
        (linha,) = sessao.scalars(select(ConsultaIcred)).all()
        assert linha.estado != DESISTIDA
    assert so_icred.estado()["icred"]["etapa"] == "consultando"
