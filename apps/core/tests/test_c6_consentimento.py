"""O SIM do cliente antes da simulação no C6 (decisão 0026, regra 3)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import Fakes
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_portabilidade_fluxo import anexo_pdf, cid, dados_extrato, idade_anos

from saturday.agent.service import AgentService
from saturday.agent.textos import CONSENTIMENTO_C6, PERGUNTA_CPF, VERSAO_CONSENTIMENTO_C6
from saturday.dados.modelos import Consentimento

CPF = "00189004967"


@pytest.fixture
def c6_ligado(service: AgentService) -> None:
    service.context = replace(service.context, c6_ativo=True)


def _extrato(client: TestClient, fakes: Fakes, conversa: str, cpf: str | None = CPF) -> str:
    fakes.llm.extrato = {**dados_extrato(), "cpf": cpf}
    resposta = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    )
    return str(resposta.json()["answer"])


def _dizer(client: TestClient, conversa: str, texto: str) -> dict:
    return dict(client.post("/chat", json={"conversation_id": conversa, "message": texto}).json())


def _provas(fabrica: sessionmaker[Session]) -> list[Consentimento]:
    with fabrica() as sessao:
        return list(sessao.scalars(select(Consentimento)))


def test_c6_desligado_nao_pede_autorizacao(client: TestClient, fakes: Fakes) -> None:
    assert "Quer seguir com a portabilidade?" in _extrato(client, fakes, cid())


@pytest.mark.usefixtures("c6_ligado")
def test_sim_grava_a_prova_e_segue(
    client: TestClient, fakes: Fakes, fabrica: sessionmaker[Session]
) -> None:
    conversa = cid()
    assert _extrato(client, fakes, conversa) == CONSENTIMENTO_C6
    assert _provas(fabrica) == []

    corpo = _dizer(client, conversa, "Sim, autorizo")

    assert corpo["portability_result"]["ok"] is True
    (prova,) = _provas(fabrica)
    assert (prova.tipo, prova.cpf, prova.versao) == ("simulacao_c6", CPF, VERSAO_CONSENTIMENTO_C6)
    assert prova.texto_mostrado == CONSENTIMENTO_C6
    assert prova.resposta_literal == "Sim, autorizo"
    assert prova.conversa_id is not None


@pytest.mark.usefixtures("c6_ligado")
def test_nao_segue_so_com_a_portabilidade_sem_prova(
    client: TestClient, fakes: Fakes, fabrica: sessionmaker[Session]
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)

    corpo = _dizer(client, conversa, "não autorizo")

    assert "Quer seguir com a portabilidade?" in corpo["answer"]
    assert _provas(fabrica) == []


@pytest.mark.usefixtures("c6_ligado")
def test_resposta_ambigua_repete_uma_vez_e_depois_segue_sem_prova(
    client: TestClient, fakes: Fakes, fabrica: sessionmaker[Session]
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)

    assert "Responda *SIM* ou *NÃO*" in _dizer(client, conversa, "pra que isso")["answer"]
    corpo = _dizer(client, conversa, "hum")

    assert "Quer seguir com a portabilidade?" in corpo["answer"]
    assert _provas(fabrica) == []


@pytest.mark.usefixtures("c6_ligado")
def test_extrato_sem_cpf_pergunta_o_cpf_antes(
    client: TestClient, fakes: Fakes, fabrica: sessionmaker[Session]
) -> None:
    conversa = cid()
    assert _extrato(client, fakes, conversa, cpf=None) == PERGUNTA_CPF

    assert _dizer(client, conversa, "001.890.049-67")["answer"] == CONSENTIMENTO_C6
    _dizer(client, conversa, "sim")

    assert [p.cpf for p in _provas(fabrica)] == [CPF]


@pytest.mark.usefixtures("c6_ligado")
def test_sim_depois_de_outra_fala_nao_vale_como_prova(
    client: TestClient, fakes: Fakes, fabrica: sessionmaker[Session]
) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)
    client.post("/chat", json={"conversation_id": conversa, "message": "   "})

    assert _dizer(client, conversa, "sim")["answer"] == CONSENTIMENTO_C6
    assert _provas(fabrica) == []
    _dizer(client, conversa, "sim")
    assert len(_provas(fabrica)) == 1


@pytest.mark.usefixtures("c6_ligado")
def test_conversa_aguardando_o_sim_aparece_na_consulta(client: TestClient, fakes: Fakes) -> None:
    conversa = cid()
    _extrato(client, fakes, conversa)

    resposta = client.get(f"/conversations/{conversa}")

    assert resposta.status_code == 200
    assert resposta.json()["aguardando"] == "consentimento_c6"


def test_cpf_numerico_na_leitura_nao_derruba_o_extrato(client: TestClient, fakes: Fakes) -> None:
    assert "Quer seguir com a portabilidade?" in _extrato(client, fakes, cid(), cpf=189004967)  # type: ignore[arg-type]


@pytest.mark.usefixtures("c6_ligado")
def test_cpf_invalido_no_extrato_nao_vale(client: TestClient, fakes: Fakes) -> None:
    assert _extrato(client, fakes, cid(), cpf="11111111111") == PERGUNTA_CPF
