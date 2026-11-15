"""Granatech simulada para membro testador (decisão 0020). Exige Postgres."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from conftest import _montar_app, settings_granatech
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update

from saturday.agent.clt.turno import PROVA_DE_TESTE, Turno
from saturday.bancos.granatech.cliente import PARCEIRO, PARCEIRO_TESTE, ClienteGranatech
from saturday.dados.modelos import ConsultaGranatech, Cota, EventoRecebido, UsuarioPainel
from saturday.dados.sessao import sessao as abrir
from saturday.jobs import granatech as jobs_granatech
from saturday.painel import sessoes

CPF = "00189004967"
TELEFONE = "11987654321"
TOKEN_SIMULADOR = "token-do-simulador-de-teste"  # noqa: S105 - token fixo de teste

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")


def _clientes(http: Any, fabrica: Any) -> tuple[ClienteGranatech, ClienteGranatech]:
    settings = settings_granatech()
    return (
        ClienteGranatech(http, settings, fabrica, dormir=lambda _s: None),
        ClienteGranatech(http, settings, fabrica, dormir=lambda _s: None, teste=True),
    )


def test_cliente_de_teste_tem_cota_propria_e_nao_mistura_consultas(http_granatech, fabrica):
    real, teste = _clientes(http_granatech, fabrica)

    de_teste = teste.abrir_consulta(CPF, "Fulano de Tal", TELEFONE)
    assert not de_teste.reaproveitada
    # A real não reaproveita a linha de teste do mesmo CPF: só a listagem remota
    # (aqui, o mesmo simulador) traz o id, e ele vira uma linha real à parte.
    de_verdade = real.abrir_consulta(CPF, "Fulano de Tal", TELEFONE)

    with abrir(fabrica) as s:
        linhas = s.scalars(select(ConsultaGranatech).order_by(ConsultaGranatech.id)).all()
        assert [(c.id_externo, c.teste) for c in linhas] == [
            (de_teste.id_externo, True),
            (de_verdade.id_externo, False),
        ]
        cotas = {c.parceiro: c.usadas for c in s.scalars(select(Cota))}
    assert cotas.get(PARCEIRO_TESTE) == 1
    assert cotas.get(PARCEIRO, 0) == 0
    assert teste.id_local_da_consulta(de_teste.id_externo) == linhas[0].id
    assert real.id_local_da_consulta(de_verdade.id_externo) == linhas[1].id


def test_webhook_do_simulador_vai_marcado_e_o_worker_so_mexe_na_linha_de_teste(service_pg, fabrica):
    api = TestClient(
        _montar_app(
            settings_granatech(granatech_simulador_webhook_token=SecretStr(TOKEN_SIMULADOR)),
            service_pg,
            fabrica,
        )
    )
    evento = {"id_solicitacao": "c1", "cpf": CPF, "status": "PROCESSING", "tipo": "CONSULTA"}
    assert (
        api.post(
            "/webhooks/granatech", json=evento, headers={"x-webhook-token": TOKEN_SIMULADOR}
        ).status_code
        == 200
    )
    assert api.post("/webhooks/granatech", json=evento).status_code == 401
    with abrir(fabrica) as s:
        [linha] = s.scalars(select(EventoRecebido)).all()
        assert linha.payload["_teste"] is True

    # Mesmo id na Granatech real e no simulador: o evento de teste só toca a de teste.
    with abrir(fabrica) as s:
        for teste in (False, True):
            s.add(
                ConsultaGranatech(
                    id_externo="c1",
                    teste=teste,
                    cpf=CPF,
                    status="AWAITING_CLIENT_AUTHORIZATION",
                    historico=[],
                )
            )
    jobs_granatech.aplicar(fabrica, None, {**evento, "_teste": True}, None)
    with abrir(fabrica) as s:
        estados = {c.teste: c.status for c in s.scalars(select(ConsultaGranatech))}
    assert estados == {False: "AWAITING_CLIENT_AUTHORIZATION", True: "PROCESSING"}


def test_aceite_de_teste_so_para_membro_com_simulador(service_pg, fabrica, http_granatech):
    _, teste = _clientes(http_granatech, fabrica)
    contexto = replace(service_pg.context, fabrica=fabrica, granatech=teste, granatech_teste=teste)

    def turno(texto: str, contexto: Any = contexto) -> Turno:
        return Turno(
            clt={}, state={"telefone": TELEFONE}, contexto=contexto, texto=texto, hoje=date.today()
        )

    # Sem o membro, nada muda: o SIM continua obrigatório.
    assert not turno("beleza").aceite_de_teste()
    with abrir(fabrica) as s:
        usuario = sessoes.criar_usuario(s, "dev@exemplo.test", "senha-bem-comprida-1", "atendente")
        s.execute(
            update(UsuarioPainel)
            .where(UsuarioPainel.id == usuario.id)
            .values(telefone=TELEFONE, pode_testar_fluxos=True)
        )

    aceitou = turno("beleza")
    assert aceitou.aceite_de_teste()
    assert aceitou.granatech is teste
    assert aceitou.resposta_da_prova() == f"{PROVA_DE_TESTE} beleza"
    assert not turno("não quero").aceite_de_teste()
    assert not turno("qual a taxa?").aceite_de_teste()
    # Sem o simulador (produção), o membro segue com a Granatech real e o SIM.
    assert not turno("beleza", replace(contexto, granatech_teste=None)).aceite_de_teste()


def test_simulador_nao_sobe_em_producao():
    settings = settings_granatech(
        environment="prod",
        granatech_simulador_url="http://simulador:8200",
        granatech_simulador_chave=SecretStr("chave"),
        granatech_simulador_webhook_token=SecretStr("token"),
    )
    with pytest.raises(RuntimeError, match="SIMULADOR_URL não vale em produção"):
        settings.validar_para_subir()
