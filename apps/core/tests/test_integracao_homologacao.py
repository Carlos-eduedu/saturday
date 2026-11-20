"""Integração do APP MEX (decisão 0035), fase 4: homologação pela integração.

As mesmas rodadas da aba Granatech (decisão 0014), pedidas com o token.
"""

from __future__ import annotations

from typing import Any

from conftest import _montar_app, entrar_como, settings_granatech
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.dados.modelos import Auditoria, HomologacaoGranatech
from saturday.dados.sessao import sessao as abrir_sessao

PAINEL = "/admin/gestao/integracoes"
ROTA = "/integracao/homologacao"


def _cliente(service: AgentService, fabrica: sessionmaker[Session], **extras: Any) -> TestClient:
    return TestClient(_montar_app(settings_granatech(**extras), service, fabrica))


def _token(client: TestClient, fabrica: sessionmaker[Session], *escopos: str) -> dict[str, str]:
    csrf = entrar_como(client, fabrica, "gestor")
    criada = client.post(PAINEL, json={"nome": "APP MEX", "escopos": list(escopos)}, headers=csrf)
    assert criada.status_code == 201, criada.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {criada.json()['token']}"}


def test_integracao_pede_rodada_uma_por_vez(service: AgentService, fabrica: Any) -> None:
    client = _cliente(service, fabrica)
    token = _token(client, fabrica, "homologacao")

    criada = client.post(ROTA, json={"fase": 1}, headers=token)
    assert criada.status_code == 201, criada.text
    assert criada.json()["pedido_por"] == "APP MEX"
    assert client.post(ROTA, json={"fase": 2}, headers=token).status_code == 409

    rodada_id = criada.json()["id"]
    assert client.get(ROTA, headers=token).json()["rodadas"][0]["pedido_por"] == "APP MEX"
    detalhe = client.get(f"{ROTA}/{rodada_id}", headers=token).json()
    assert detalhe["itens_previstos"]
    zipado = client.get(f"{ROTA}/{rodada_id}/zip", headers=token)
    assert zipado.headers["content-type"] == "application/zip"

    with abrir_sessao(fabrica) as sessao:
        rodada = sessao.scalars(select(HomologacaoGranatech)).one()
        assert rodada.pedido_por is None and rodada.integracao_id is not None
        (auditoria,) = sessao.scalars(
            select(Auditoria).where(Auditoria.acao == "granatech:homologacao")
        ).all()
        assert auditoria.usuario_id is None
        assert auditoria.detalhe is not None and auditoria.detalhe["origem"] == "integracao"


def test_painel_mostra_o_nome_da_integracao(service: AgentService, fabrica: Any) -> None:
    client = _cliente(service, fabrica)
    token = _token(client, fabrica, "homologacao")
    client.post(ROTA, json={"fase": 1}, headers=token)

    entrar_como(client, fabrica, "gestor")
    (rodada,) = client.get("/admin/granatech/homologacao").json()["rodadas"]
    assert rodada["pedido_por"] == "APP MEX"


def test_sem_o_escopo_403(service: AgentService, fabrica: Any) -> None:
    client = _cliente(service, fabrica)
    token = _token(client, fabrica, "leitura")
    assert client.get(ROTA, headers=token).status_code == 403
    assert client.post(ROTA, json={"fase": 1}, headers=token).status_code == 403


def test_indisponivel_com_a_granatech_de_producao(service: AgentService, fabrica: Any) -> None:
    client = _cliente(service, fabrica, granatech_base_url="https://api.granatech.com.br")
    token = _token(client, fabrica, "homologacao")
    assert client.get(ROTA, headers=token).status_code == 404
    assert client.post(ROTA, json={"fase": 1}, headers=token).status_code == 404
