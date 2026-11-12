"""Aba Granatech do painel (decisão 0013), ponta a ponta.

Mesmo arranjo das jornadas CLT (`test_clt_proposta.py`): Postgres real,
simulador da Granatech em processo e a API do painel por cima.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from conftest import _montar_app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_clt_jornada import (  # noqa: F401 - fixtures
    ATE_CONSENTIMENTO,
    Jornada,
    _ate_oferta,
    brasilapi,
    fakes_clt,
)
from test_clt_jornada import nova as _nova_fase5  # noqa: F401
from test_clt_proposta import (
    DADOS_ATE_RESUMO,
    _ate_proposta,
    _atendimento,
    _evento,
    _posts_de_proposta,
    _proposta,
    _saidas,
    _ultimo_payload,
    nova,  # noqa: F401 - fixture
)

from saturday.agent.clt.mensagens import texto
from saturday.dados.modelos import (
    Auditoria,
    ConsultaGranatech,
    Conversa,
    PropostaGranatech,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import sessoes
from saturday.web.api.granatech_admin import SEM_CONVERSA, acoes_da_proposta

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
ROTA = "/admin/granatech"


@pytest.fixture
def painel(nova: Any, fabrica: sessionmaker[Session]) -> Any:  # noqa: F811
    def criar(**extras: Any) -> tuple[Jornada, TestClient]:
        jornada: Jornada = nova(**extras)
        # Sem `with`: o lifespan montaria outro serviço e outra fábrica.
        app = _montar_app(jornada.servico.settings, jornada.servico, fabrica)
        return jornada, TestClient(app)

    return criar


def _entrar(client: TestClient, fabrica: sessionmaker[Session], perfil: str) -> dict[str, str]:
    email = f"{perfil}-{uuid.uuid4().hex[:6]}@exemplo.test"
    with abrir_sessao(fabrica) as sessao:
        sessoes.criar_usuario(sessao, email, SENHA, perfil)
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200, resposta.text
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _id_proposta(fabrica: sessionmaker[Session]) -> int:
    with abrir_sessao(fabrica) as sessao:
        return int(sessao.scalars(select(PropostaGranatech.id)).one())


def _auditoria(fabrica: sessionmaker[Session], acao: str) -> list[Any]:
    with abrir_sessao(fabrica) as sessao:
        return list(sessao.scalars(select(Auditoria.detalhe).where(Auditoria.acao == acao)).all())


def _conversa_uuid(jornada: Jornada) -> uuid.UUID:
    with abrir_sessao(jornada.fabrica) as sessao:
        return sessao.scalars(
            select(Conversa.id).where(Conversa.conversation_id == jornada.id)
        ).one()


@pytest.fixture
def com_handoff_incerto(
    simulador_granatech: ModuleType, http_granatech: TestClient
) -> Iterator[None]:
    """POST da proposta com timeout (criada no banco) e listagem fora do ar."""

    simulador_granatech.CONFIG["timeout_s"] = 0
    http_granatech.post(
        "/admin/falha",
        json={"rota": "/propostas", "metodo": "POST", "status": "timeout", "registrar": True},
    )
    http_granatech.post(
        "/admin/falha",
        json={"rota": "/propostas/lista", "metodo": "GET", "status": 500, "vezes": 2},
    )
    yield


def _ate_handoff_incerto(jornada: Jornada) -> None:
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)
    resposta = jornada.falar("SIM")
    assert resposta.status == "handoff"
    assert _atendimento(jornada) == "handoff"


# ---------------------------------------------------------------- leitura


def test_atendente_le_com_cpf_mascarado_mas_nao_age(
    painel: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada, client = painel()
    _ate_proposta(jornada)
    cabecalhos = _entrar(client, fabrica, "atendente")

    [linha] = client.get(f"{ROTA}/propostas").json()
    assert "*" in linha["cpf"]
    assert linha["conversa_id"] == str(_conversa_uuid(jornada))
    detalhe = client.get(f"{ROTA}/propostas/{linha['id']}").json()
    assert detalhe["etapa"] == "proposta"
    assert detalhe["oferta"] is not None
    consulta = client.get(f"{ROTA}/consultas/{linha['consulta_id']}").json()
    assert consulta["vinculos"] and "pessoa_natural" not in consulta

    assert client.get(f"{ROTA}/propostas", params={"cpf": "123"}).status_code == 422
    resposta = client.post(
        f"{ROTA}/propostas/{linha['id']}/cancelar", json={"motivo": "teste"}, headers=cabecalhos
    )
    assert resposta.status_code == 403

    revelado = client.post(
        f"{ROTA}/consultas/{linha['consulta_id']}/revelar", headers=cabecalhos
    ).json()
    assert len(revelado["valor"]) == 11
    assert _auditoria(fabrica, "revelar:cpf") == [None]


def test_sem_conversa_nao_tem_acao() -> None:
    linha = PropostaGranatech(
        conversa_id=None, estado_envio="incerta", id_externo="x", status="PENDING_FORMALIZATION"
    )
    assert set(acoes_da_proposta(linha, True).values()) == {SEM_CONVERSA}


# ---------------------------------------------------------------- reconciliar


@pytest.mark.usefixtures("com_handoff_incerto")
def test_reconciliar_achada_segue_a_jornada_sem_novo_post(
    painel: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    jornada, client = painel()
    _ate_handoff_incerto(jornada)
    cabecalhos = _entrar(client, fabrica, "gestor")
    proposta_id = _id_proposta(fabrica)

    resposta = client.post(f"{ROTA}/propostas/{proposta_id}/reconciliar", headers=cabecalhos)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["achada"] is True

    assert _posts_de_proposta(simulador_granatech) == 1
    assert _atendimento(jornada) == "ia"
    assert jornada.clt()["etapa"] == "proposta"
    assert "dados_tomador" in simulador_granatech.PROPOSTAS[_proposta(jornada)]
    assert _auditoria(fabrica, "granatech_reconciliar") == [None]
    assert len(_auditoria(fabrica, "devolver")) == 1

    # Já reconciliada: a ação deixa de valer.
    de_novo = client.post(f"{ROTA}/propostas/{proposta_id}/reconciliar", headers=cabecalhos)
    assert de_novo.status_code == 409


def test_reconciliar_nao_achada_fica_em_handoff(
    painel: Any,
    fabrica: sessionmaker[Session],
    simulador_granatech: ModuleType,
    http_granatech: TestClient,
) -> None:
    simulador_granatech.CONFIG["timeout_s"] = 0
    http_granatech.post(
        "/admin/falha", json={"rota": "/propostas", "metodo": "POST", "status": "timeout"}
    )
    jornada, client = painel()
    _ate_handoff_incerto(jornada)
    cabecalhos = _entrar(client, fabrica, "gestor")

    resposta = client.post(
        f"{ROTA}/propostas/{_id_proposta(fabrica)}/reconciliar", headers=cabecalhos
    )
    assert resposta.json() == {"achada": False}
    assert _atendimento(jornada) == "handoff"
    assert _posts_de_proposta(simulador_granatech) == 1


# ---------------------------------------------------------------- link, cancelar, conta


def test_reenviar_link_fala_mesmo_com_a_conversa_assumida(
    painel: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada, client = painel()
    _ate_proposta(jornada)
    cabecalhos = _entrar(client, fabrica, "gestor")
    proposta_id = _id_proposta(fabrica)
    rota = f"{ROTA}/propostas/{proposta_id}/reenviar-link"

    assert client.post(rota, headers=cabecalhos).status_code == 409
    _evento(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO")
    conversa = _conversa_uuid(jornada)
    assert (
        client.post(f"/admin/conversas/{conversa}/assumir", headers=cabecalhos).status_code == 204
    )
    antes = _saidas(jornada)

    assert client.post(rota, headers=cabecalhos).status_code == 204
    assert _saidas(jornada) == antes + 1
    assert _ultimo_payload(jornada)["link_aviso"]
    assert _atendimento(jornada) == "assumida"


def test_cancelar_exige_motivo_audita_e_nao_avisa_no_clique(
    painel: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    jornada, client = painel()
    _ate_proposta(jornada)
    cabecalhos = _entrar(client, fabrica, "gestor")
    rota = f"{ROTA}/propostas/{_id_proposta(fabrica)}/cancelar"
    antes = _saidas(jornada)

    assert client.post(rota, json={"motivo": ""}, headers=cabecalhos).status_code == 422
    resposta = client.post(rota, json={"motivo": "cliente desistiu"}, headers=cabecalhos)
    assert resposta.status_code == 204
    assert _auditoria(fabrica, "granatech_cancelar") == [{"motivo": "cliente desistiu"}]
    assert any(
        metodo == "POST" and caminho.endswith("/cancelar")
        for metodo, caminho in simulador_granatech.CHAMADAS
    )
    assert _saidas(jornada) == antes


def test_corrigir_conta_so_com_a_flag_e_banco_da_lista(
    painel: Any, fabrica: sessionmaker[Session]
) -> None:
    conta = {
        "banco_codigo": "341",
        "agencia": "1234",
        "numero_conta": "998877",
        "digito_conta": "5",
        "tipo_conta": "conta_corrente",
    }
    desligada, client_off = painel()
    _ate_proposta(desligada)
    cabecalhos = _entrar(client_off, fabrica, "gestor")
    rota = f"{ROTA}/propostas/{_id_proposta(fabrica)}/conta"
    assert client_off.post(rota, json=conta, headers=cabecalhos).status_code == 404


def test_corrigir_conta_com_a_flag(painel: Any, fabrica: sessionmaker[Session]) -> None:
    conta = {
        "banco_codigo": "999",
        "agencia": "1234",
        "numero_conta": "998877",
        "digito_conta": "5",
        "tipo_conta": "conta_corrente",
    }
    jornada, client = painel(granatech_dados_bancarios_ativo=True)
    _ate_proposta(jornada)
    cabecalhos = _entrar(client, fabrica, "gestor")
    rota = f"{ROTA}/propostas/{_id_proposta(fabrica)}/conta"

    assert client.post(rota, json=conta, headers=cabecalhos).status_code == 422
    resposta = client.post(rota, json={**conta, "banco_codigo": "341"}, headers=cabecalhos)
    assert resposta.status_code == 204, resposta.text
    assert _auditoria(fabrica, "granatech_corrigir_conta") == [
        {"banco": "341", "final_conta": "77"}
    ]


# ---------------------------------------------------------------- consulta parada


def test_atualizar_detalhe_destrava_a_consulta(painel: Any, fabrica: sessionmaker[Session]) -> None:
    jornada, client = painel()
    assert jornada.roteiro(*ATE_CONSENTIMENTO, "SIM").answer == texto("consultando")
    cabecalhos = _entrar(client, fabrica, "gestor")
    with abrir_sessao(fabrica) as sessao:
        consulta_id = sessao.scalars(select(ConsultaGranatech.id)).one()

    rota = f"{ROTA}/consultas/{consulta_id}/atualizar-detalhe"
    resposta = client.post(rota, headers=cabecalhos)
    assert resposta.json() == {"pronto": True}
    assert jornada.clt()["etapa"] == "escolha_vinculo"
    with abrir_sessao(fabrica) as sessao:
        assert sessao.get(ConsultaGranatech, consulta_id).status == "SUCCESS"  # type: ignore[union-attr]
    assert client.post(rota, headers=cabecalhos).status_code == 409
