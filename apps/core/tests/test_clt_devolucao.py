"""CLT: o SIM depois da devolução pelo atendente (issue 44, decisão 0033).

Um SIM só vale para o último pedido que o cliente viu. Depois que um atendente
assume e a conversa volta à IA, o "sim" não responde ao pedido de antes: o
pedido sai de novo e só o "sim" seguinte vale. Mesmo arranjo das jornadas do
CLT: Postgres real e o simulador da Granatech em processo.
"""

from __future__ import annotations

from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest
from conftest import _montar_app, entrar_como
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from test_clt_jornada import (  # noqa: F401 - fixtures
    ATE_CONSENTIMENTO,
    Jornada,
    _ate_oferta,
    brasilapi,
    fakes_clt,
)
from test_clt_jornada import nova as _nova_fase5  # noqa: F401

from saturday.agent.clt.mensagens import texto
from saturday.agent.service import AgentService
from saturday.agent.state import ultima_mensagem_agente
from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import (
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Cota,
    Mensagem,
    PropostaGranatech,
    Recontato,
    UsuarioPainel,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as eventos_granatech

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

LIBERACOES = ["devolver", "liberar", "prazo"]


@pytest.fixture
def nova(_nova_fase5: Any) -> Any:  # noqa: F811
    def criar(**extras: Any) -> Jornada:
        jornada: Jornada = _nova_fase5(**{"granatech_proposta_ativa": True, **extras})
        return jornada

    return criar


def _atendente_no_meio(jornada: Jornada, liberacao: str = "devolver") -> None:
    """Um atendente assume a conversa, e ela volta à IA por um dos três caminhos.

    No `prazo`, quem devolve é o próprio turno seguinte do cliente.
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
        jornada.servico.settings.handoff_auto_release_horas = 1
        with abrir_sessao(jornada.fabrica) as sessao:
            sessao.execute(
                update(Conversa)
                .where(Conversa.conversation_id == jornada.id)
                .values(atendimento="handoff", atendimento_em=func.now() - timedelta(hours=2))
            )


def _provas(jornada: Jornada) -> list[tuple[str, str, str]]:
    with abrir_sessao(jornada.fabrica) as sessao:
        return [
            (p.tipo, p.texto_mostrado, p.resposta_literal)
            for p in sessao.scalars(select(Consentimento).order_by(Consentimento.id))
        ]


def _nada_consultado(fabrica: sessionmaker[Session], simulador: ModuleType) -> bool:
    """Nenhuma consulta no banco nem no simulador, e a cota intacta."""

    with abrir_sessao(fabrica) as sessao:
        consultas = sessao.scalar(select(func.count()).select_from(ConsultaGranatech))
        cota = sessao.scalar(select(func.coalesce(func.sum(Cota.usadas), 0)))
    return consultas == 0 and cota == 0 and not simulador.CONSULTAS


def _chave_da_ultima_saida(jornada: Jornada) -> str | None:
    with abrir_sessao(jornada.fabrica) as sessao:
        return sessao.scalars(
            select(Mensagem.chave_mensagem)
            .where(Mensagem.direcao == "saida")
            .order_by(Mensagem.id.desc())
        ).first()


# ---------------------------------------------------------------- consulta


@pytest.mark.parametrize("liberacao", LIBERACOES)
def test_sim_depois_do_atendente_refaz_o_pedido_da_consulta(
    nova: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType, liberacao: str
) -> None:
    jornada = nova()
    assert jornada.roteiro(*ATE_CONSENTIMENTO).answer == texto("consentimento")
    _atendente_no_meio(jornada, liberacao)

    # O cliente conversou com o atendente depois do pedido: o SIM não é dele.
    resposta = jornada.falar("sim")

    assert (resposta.status, resposta.answer) == ("answered", texto("consentimento"))
    assert _chave_da_ultima_saida(jornada) == "consentimento"
    assert _provas(jornada) == []
    assert _nada_consultado(fabrica, simulador_granatech)

    assert jornada.falar("sim").answer == texto("consultando")
    assert _provas(jornada) == [("consulta", texto("consentimento"), "sim")]
    assert len(simulador_granatech.CONSULTAS) == 1


def test_nao_depois_do_atendente_continua_valendo(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)
    _atendente_no_meio(jornada)

    assert jornada.falar("não").answer == texto("consentimento_recusado")
    assert _provas(jornada) == []


def test_sim_com_a_consulta_aberta_depois_do_atendente_nao_faz_nada_de_novo(
    nova: Any, simulador_granatech: ModuleType
) -> None:
    jornada = nova()
    assert jornada.roteiro(*ATE_CONSENTIMENTO, "SIM").answer == texto("consultando")
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == texto("aguardando_consulta")

    assert jornada.clt()["etapa"] == "consultando"
    assert len(_provas(jornada)) == 1
    assert len(simulador_granatech.CONSULTAS) == 1


# ---------------------------------------------------------------- oferta


def test_sim_depois_do_atendente_refaz_a_oferta(nova: Any) -> None:
    jornada = nova()
    oferta = _ate_oferta(jornada).answer
    assert "Boa notícia, Cliente!" in oferta
    _atendente_no_meio(jornada)

    resposta = jornada.falar("sim, quero")

    assert (resposta.status, resposta.answer) == ("answered", oferta)
    assert _chave_da_ultima_saida(jornada) == "aviso_teto+oferta"
    assert jornada.clt()["etapa"] == "oferta"

    assert jornada.falar("sim, quero").answer.startswith("Para montar a proposta")
    assert jornada.clt()["etapa"] == "dados_proposta"


def test_pedido_de_mudanca_depois_do_atendente_simula_como_antes(nova: Any) -> None:
    jornada = nova()
    oferta = _ate_oferta(jornada).answer
    _atendente_no_meio(jornada)

    resposta = jornada.falar("quero em 36 parcelas")

    assert resposta.answer != oferta and "36 parcelas" in resposta.answer


# ---------------------------------------------------------------- confirmações

DADOS_ATE_RESUMO = ("quero", "sim", "sim", "casado", "itau", "corrente", "1234", "12345-6", "sim")


@pytest.mark.parametrize(
    ("respondidas", "chave", "passo_seguinte"),
    [
        (1, "confirmar_mae", "endereco"),
        (2, "confirmar_endereco", "estado_civil"),
        (8, "confirmar_titular", "sim"),
    ],
)
def test_sim_depois_do_atendente_refaz_a_confirmacao_do_dado(
    nova: Any, respondidas: int, chave: str, passo_seguinte: str
) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    pergunta = jornada.roteiro(*DADOS_ATE_RESUMO[:respondidas]).answer
    passo = jornada.clt()["passo"]
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == pergunta
    assert _chave_da_ultima_saida(jornada) == chave
    assert jornada.clt()["passo"] == passo

    jornada.falar("sim")
    assert jornada.clt()["passo"] == passo_seguinte


def test_nao_na_confirmacao_depois_do_atendente_continua_valendo(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro("quero")
    _atendente_no_meio(jornada)

    resposta = jornada.falar("não")

    assert (resposta.status, resposta.handoff_reason) == ("handoff", "dados_divergentes")


def test_sim_depois_do_atendente_refaz_a_confirmacao_do_celular(nova: Any) -> None:
    jornada = nova()
    pergunta = jornada.roteiro(*ATE_CONSENTIMENTO[:-1]).answer
    assert pergunta.startswith("O celular para o termo é o")
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == pergunta
    assert _chave_da_ultima_saida(jornada) == "confirmar_celular"
    assert jornada.falar("sim").answer == texto("consentimento")


def test_sim_depois_do_atendente_refaz_a_pergunta_da_triagem(nova: Any) -> None:
    jornada = nova()
    pergunta = jornada.roteiro("Quero o crédito CLT").answer
    _atendente_no_meio(jornada)

    # A abertura não volta: só a pergunta que estava em aberto.
    assert jornada.falar("sim").answer == texto("triagem_carteira")
    assert pergunta.endswith(texto("triagem_carteira"))
    assert jornada.clt()["passo"] == "carteira"
    assert jornada.falar("sim").answer == texto("triagem_tempo_casa")


def test_contrato_especial_depois_do_atendente_le_a_resposta_como_a_etapa(nova: Any) -> None:
    jornada = nova()
    pergunta = jornada.roteiro("Quero o crédito CLT", "sim", "3 anos").answer
    assert pergunta == texto("triagem_contrato_especial")
    _atendente_no_meio(jornada)

    # "Sou efetivo" é o "não" desta pergunta: segue, não é refeita.
    assert jornada.falar("sou efetivo").answer == texto("triagem_granatech")


def test_sim_ao_contrato_especial_depois_do_atendente_refaz_a_pergunta(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro("Quero o crédito CLT", "sim", "3 anos")
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == texto("triagem_contrato_especial")
    assert jornada.clt()["etapa"] == "triagem"


def test_sim_depois_do_atendente_refaz_o_pedido_de_recontato(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    pedido = jornada.roteiro("Quero o crédito CLT", "sim", "8 meses").answer
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == pedido
    assert _chave_da_ultima_saida(jornada) == "recontato_tempo_casa"
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Recontato)) == 0
        assert sessao.scalars(select(Conversa.marketing)).one() != "opt_in"

    assert jornada.falar("sim").answer.startswith("Combinado")
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(Recontato.motivo)).one() == "tempo_casa"
        assert sessao.scalars(select(Conversa.marketing)).one() == "opt_in"


# ---------------------------------------------------------------- proposta


def _posts_de_proposta(simulador: ModuleType) -> int:
    return sum(
        1
        for metodo, caminho in simulador.CHAMADAS
        if metodo == "POST" and caminho.endswith("/propostas")
    )


def _propostas_gravadas(fabrica: sessionmaker[Session]) -> int:
    """Intenções e propostas: a intenção é a linha gravada antes do POST."""

    with abrir_sessao(fabrica) as sessao:
        return int(sessao.scalar(select(func.count()).select_from(PropostaGranatech)) or 0)


def _evento_da_proposta(jornada: Jornada, status: str, notificacao: str) -> None:
    payload = {
        "tipo": "proposta",
        "status_da_proposta": status,
        "tipo_notificacao": notificacao,
        "id_proposta": str(jornada.clt()["proposta"]),
    }
    eventos_granatech.aplicar(jornada.fabrica, jornada.cliente, payload, jornada.servico)


def test_sim_depois_do_atendente_refaz_o_resumo_e_nao_cria_a_proposta(
    nova: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    resumo = jornada.roteiro(*DADOS_ATE_RESUMO).answer
    assert resumo.startswith("Confira o resumo da proposta")
    _atendente_no_meio(jornada)

    resposta = jornada.falar("SIM")

    assert (resposta.status, resposta.answer) == ("answered", resumo)
    assert _chave_da_ultima_saida(jornada) == "resumo_aceite"
    assert [tipo for tipo, _, _ in _provas(jornada)] == ["consulta"]
    # Regra 4: nem intenção nem POST.
    assert _propostas_gravadas(fabrica) == 0
    assert _posts_de_proposta(simulador_granatech) == 0

    assert jornada.falar("SIM").answer == texto("proposta_enviada")
    assert _provas(jornada)[-1] == ("proposta", resumo, "SIM")
    assert _propostas_gravadas(fabrica) == 1
    assert _posts_de_proposta(simulador_granatech) == 1


def test_nao_ao_resumo_depois_do_atendente_continua_valendo(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)
    _atendente_no_meio(jornada)

    assert jornada.falar("não").answer == texto("aceite_recusado")
    assert jornada.clt()["etapa"] == "oferta"


@pytest.mark.parametrize("formalizando", [False, True])
def test_sim_com_a_proposta_criada_depois_do_atendente_nao_cria_outra(
    nova: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType, formalizando: bool
) -> None:
    jornada = nova(dominio_publico="saturday.exemplo")
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)
    assert jornada.falar("SIM").answer == texto("proposta_enviada")
    if formalizando:
        _evento_da_proposta(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO")
    etapa = jornada.clt()["etapa"]
    assert etapa == ("formalizacao" if formalizando else "proposta")
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == texto("acompanhando")

    assert jornada.clt()["etapa"] == etapa
    assert [tipo for tipo, _, _ in _provas(jornada)] == ["consulta", "proposta"]
    assert _propostas_gravadas(fabrica) == 1
    assert _posts_de_proposta(simulador_granatech) == 1


def test_sim_depois_do_atendente_refaz_a_confirmacao_da_conta_nova(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO, "SIM")
    _evento_da_proposta(jornada, "PENDING_USER_REVIEW", "FALHA_PAGAMENTO")
    jornada.roteiro("001", "poupança", "4321-0")
    assert jornada.falar("998877").answer == texto("confirmar_titular")
    _atendente_no_meio(jornada)

    assert jornada.falar("sim").answer == texto("confirmar_titular")
    assert jornada.clt()["etapa"] == "nova_conta"

    resposta = jornada.falar("sim")
    assert (resposta.status, resposta.handoff_reason) == ("handoff", "falha_pagamento")


# ---------------------------------------------------------------- "Desfazer" do painel


def assumir_e_desfazer(
    servico: AgentService, fabrica: sessionmaker[Session], conversation_id: str, *, escreve: bool
) -> None:
    """Pelo painel: o atendente assume, escreve (ou não) ao cliente e desfaz."""

    painel = TestClient(_montar_app(servico.settings, servico, fabrica))
    csrf = entrar_como(painel, fabrica, "atendente")
    with abrir_sessao(fabrica) as sessao:
        alvo = sessao.scalars(
            select(Conversa.id).where(Conversa.conversation_id == conversation_id)
        ).one()
    rota = f"/admin/conversas/{alvo}"
    assert painel.post(f"{rota}/assumir", headers=csrf).status_code == 204
    if escreve:
        enviada = painel.post(f"{rota}/mensagens", headers=csrf, json={"texto": "Oi, sou a Ana."})
        assert enviada.status_code == 201, enviada.text
    assert painel.post(f"{rota}/desfazer", headers=csrf).status_code == 204


def test_sim_depois_de_o_atendente_escrever_e_desfazer_refaz_o_pedido(
    nova: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)
    assumir_e_desfazer(jornada.servico, fabrica, jornada.id, escreve=True)

    assert jornada.falar("sim").answer == texto("consentimento")
    assert _provas(jornada) == []
    assert _nada_consultado(fabrica, simulador_granatech)

    assert jornada.falar("sim").answer == texto("consultando")
    assert _provas(jornada) == [("consulta", texto("consentimento"), "sim")]


def test_desfazer_que_volta_ao_handoff_nao_deixa_a_marca(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(update(Conversa).values(atendimento="handoff"))

    # O atendente assume um handoff, escreve e desfaz: a conversa volta ao
    # handoff, não à IA. A marca fica para quando ela for devolvida.
    assumir_e_desfazer(jornada.servico, fabrica, jornada.id, escreve=True)

    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(Conversa.atendimento)).one() == "handoff"
    estado = jornada.servico.estado_atual(jornada.servico.config(jornada.id))
    assert ultima_mensagem_agente(estado) == texto("consentimento")


def test_sim_depois_de_desfazer_sem_o_atendente_escrever_vale(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)
    assumir_e_desfazer(jornada.servico, fabrica, jornada.id, escreve=False)

    # O pedido continua sendo a última coisa que o cliente viu.
    assert jornada.falar("sim").answer == texto("consultando")
    assert _provas(jornada) == [("consulta", texto("consentimento"), "sim")]
