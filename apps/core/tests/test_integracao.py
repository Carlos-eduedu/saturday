"""Integração do APP MEX (decisão 0035), fase 1: tokens e proxy de leitura.

Postgres real, simulador da Granatech em processo e a API por cima.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from conftest import entrar_como, settings_granatech
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.dados.modelos import Auditoria, ConsultaGranatech, Integracao
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.web.api.integracao_granatech import get_granatech

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

PAINEL = "/admin/gestao/integracoes"
PROXY = "/integracao/granatech/api-consignado/v1"


@pytest.fixture
def api(
    client_pg: TestClient, http_granatech: TestClient, fabrica: sessionmaker[Session]
) -> TestClient:
    cliente = ClienteGranatech(
        http_granatech, settings_granatech(), fabrica, dormir=lambda _s: None
    )
    client_pg.app.dependency_overrides[get_granatech] = lambda: cliente  # type: ignore[attr-defined]
    return client_pg


def _token(api: TestClient, fabrica: sessionmaker[Session], *escopos: str) -> dict[str, str]:
    csrf = entrar_como(api, fabrica, "gestor")
    resposta = api.post(PAINEL, json={"nome": "APP MEX", "escopos": list(escopos)}, headers=csrf)
    assert resposta.status_code == 201, resposta.text
    api.cookies.clear()  # o proxy não usa a sessão do painel
    return {"Authorization": f"Bearer {resposta.json()['token']}"}


def _auditoria(fabrica: sessionmaker[Session], acao: str) -> list[Auditoria]:
    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.scalars(select(Auditoria).where(Auditoria.acao == acao)).all()
        sessao.expunge_all()
        return list(linhas)


# ------------------------------------------------------------------ painel


def test_so_o_gestor_cria_e_o_token_sai_uma_vez(api: TestClient, fabrica: Any) -> None:
    csrf = entrar_como(api, fabrica, "atendente")
    assert (
        api.post(PAINEL, json={"nome": "x", "escopos": ["leitura"]}, headers=csrf).status_code
        == 403
    )

    csrf = entrar_como(api, fabrica, "gestor")
    criada = api.post(PAINEL, json={"nome": "APP MEX", "escopos": ["leitura"]}, headers=csrf)
    assert criada.status_code == 201
    token = criada.json()["token"]
    assert token.startswith("sat_")

    lista = api.get(PAINEL).json()
    assert [i["nome"] for i in lista] == ["APP MEX"]
    assert "token" not in lista[0]
    with abrir_sessao(fabrica) as sessao:
        assert token not in sessao.scalars(select(Integracao.token_hash)).one()
    assert _auditoria(fabrica, "integracao_criar")[0].detalhe == {
        "nome": "APP MEX",
        "escopos": ["leitura"],
    }


def test_escopo_desconhecido_e_recusado(api: TestClient, fabrica: Any) -> None:
    csrf = entrar_como(api, fabrica, "gestor")
    assert (
        api.post(PAINEL, json={"nome": "x", "escopos": ["tudo"]}, headers=csrf).status_code == 422
    )


def test_token_revogado_para_de_valer(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    assert api.get("/integracao/cota", headers=token).status_code == 200

    csrf = entrar_como(api, fabrica, "gestor")
    integracao_id = api.get(PAINEL).json()[0]["id"]
    assert api.post(f"{PAINEL}/{integracao_id}/revogar", headers=csrf).status_code == 204
    assert api.post(f"{PAINEL}/{integracao_id}/revogar", headers=csrf).status_code == 404
    api.cookies.clear()

    assert api.get("/integracao/cota", headers=token).status_code == 401
    assert len(_auditoria(fabrica, "integracao_revogar")) == 1


# ------------------------------------------------------------------ autenticação


def test_sem_token_ou_com_token_errado_401(api: TestClient) -> None:
    assert api.get("/integracao/cota").status_code == 401
    assert api.get("/integracao/cota", headers={"Authorization": "Bearer sat_x"}).status_code == 401
    assert api.get("/integracao/cota", headers={"Authorization": "sat_x"}).status_code == 401


def test_sem_o_escopo_403(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "revelar")
    assert api.get("/integracao/cota", headers=token).status_code == 403


def test_uso_fica_registrado(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    api.get("/integracao/cota", headers=token)
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(Integracao.ultimo_uso_em)).one() is not None


# ------------------------------------------------------------------ proxy


def test_proxy_devolve_o_corpo_da_granatech(
    api: TestClient, fabrica: Any, http_granatech: TestClient
) -> None:
    token = _token(api, fabrica, "leitura")
    resposta = api.get(f"{PROXY}/bancos", headers=token)
    assert resposta.status_code == 200

    # Cru, como a Granatech manda: o painel filtra os desabilitados, o proxy não.
    login = http_granatech.post("/api/v1/auth/login", json={"chave_api": "chave-do-simulador"})
    direto = http_granatech.get(
        f"{PROXY.removeprefix('/integracao/granatech')}/bancos",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert resposta.json() == direto.json()


def test_proxy_repassa_a_recusa_da_granatech(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    resposta = api.get(f"{PROXY}/propostas/nao-existe", headers=token)
    assert resposta.status_code == 404
    assert resposta.json() == {"message": "proposta não encontrada"}


def test_proxy_repassa_a_busca(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    resposta = api.get(
        f"{PROXY}/consulta-saldo/usuario",
        params={"pagina": 1, "filtrar_por": "cpf", "valor_filtro": "52998224725"},
        headers=token,
    )
    assert resposta.status_code == 200


def test_rota_fora_da_lista_404(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    assert api.get(f"{PROXY}/tools/cpf", headers=token).status_code == 404
    assert api.post(f"{PROXY}/propostas", json={}, headers=token).status_code == 404
    assert api.post(f"{PROXY}/bancos", headers=token).status_code == 405


# ------------------------------------------------------------------ rotas do Saturday


def test_cota(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    corpo = api.get("/integracao/cota", headers=token).json()
    assert corpo["dia"]["usadas"] == 0 and corpo["mes"]["usadas"] == 0


def test_revelar_audita_com_a_origem(api: TestClient, fabrica: Any) -> None:
    with abrir_sessao(fabrica) as sessao:
        sessao.add(ConsultaGranatech(id_externo="ext-1", cpf="52998224725", status="pendente"))
    token = _token(api, fabrica, "revelar")

    assert api.post("/integracao/consultas/nao-existe/revelar", headers=token).status_code == 404
    resposta = api.post("/integracao/consultas/ext-1/revelar", headers=token)
    assert resposta.json() == {"campo": "cpf", "valor": "52998224725"}

    (linha,) = _auditoria(fabrica, "revelar:cpf")
    assert linha.usuario_id is None
    assert linha.detalhe is not None and linha.detalhe["origem"] == "integracao"


# ------------------------------------------------------------------ falhas da Granatech


def _api_com(
    client_pg: TestClient,
    fabrica: sessionmaker[Session],
    rota: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """Granatech de mentira: login aceito e o resto respondido por `rota`."""

    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"token": "t", "expira_em": "1h"})
        pedidos.append(pedido)
        return rota(pedido)

    http = httpx.Client(transport=httpx.MockTransport(responder), base_url="http://granatech")
    cliente = ClienteGranatech(http, settings_granatech(), fabrica, dormir=lambda _s: None)
    client_pg.app.dependency_overrides[get_granatech] = lambda: cliente  # type: ignore[attr-defined]
    return pedidos


def test_busca_chega_a_granatech_com_os_parametros(client_pg: TestClient, fabrica: Any) -> None:
    pedidos = _api_com(client_pg, fabrica, lambda _p: httpx.Response(200, json={"dados": []}))
    token = _token(client_pg, fabrica, "leitura")
    resposta = client_pg.get(
        f"{PROXY}/propostas/lista?termo_busca=52998224725&status=A&status=B", headers=token
    )
    assert resposta.status_code == 200
    assert pedidos[0].url.params.multi_items() == [
        ("termo_busca", "52998224725"),
        ("status", "A"),
        ("status", "B"),
    ]


def test_falha_da_granatech_vira_502(client_pg: TestClient, fabrica: Any) -> None:
    pedidos = _api_com(client_pg, fabrica, lambda _p: httpx.Response(503))
    token = _token(client_pg, fabrica, "leitura")
    assert client_pg.get(f"{PROXY}/bancos", headers=token).status_code == 502
    assert len(pedidos) == 2  # o GET tenta de novo uma vez


def test_recusa_do_login_da_mex_nao_parece_recusa_do_token(
    client_pg: TestClient, fabrica: Any
) -> None:
    # 401 e 403 da Granatech são do login da MEX; o APP MEX leria como token revogado.
    _api_com(client_pg, fabrica, lambda _p: httpx.Response(401, json={"message": "não"}))
    token = _token(client_pg, fabrica, "leitura")
    assert client_pg.get(f"{PROXY}/bancos", headers=token).status_code == 502


def test_granatech_desligada_503(client_pg: TestClient, fabrica: Any) -> None:
    token = _token(client_pg, fabrica, "leitura")
    assert client_pg.get(f"{PROXY}/bancos", headers=token).status_code == 503


def test_id_que_sairia_da_lista_e_recusado(client_pg: TestClient, fabrica: Any) -> None:
    pedidos = _api_com(client_pg, fabrica, lambda _p: httpx.Response(200, json={}))
    token = _token(client_pg, fabrica, "leitura")
    assert client_pg.get(f"{PROXY}/propostas/x%3Fa%3Db", headers=token).status_code == 422
    assert client_pg.get(f"{PROXY}/consulta-saldo/a.b", headers=token).status_code == 422
    assert pedidos == []
