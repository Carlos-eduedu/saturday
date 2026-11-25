"""Integração do APP MEX (decisão 0035), fase 3: proxy de escrita.

Postgres real e o simulador da Granatech em processo; o caso incerto usa uma
Granatech de mentira, que não responde ao POST da proposta.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from conftest import entrar_como, settings_granatech
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.dados.modelos import (
    ConsultaGranatech,
    Cota,
    Integracao,
    Outbox,
    PropostaGranatech,
    SimulacaoIntegracao,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as jobs
from saturday.web.api.integracao_granatech import get_granatech

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

PAINEL = "/admin/gestao/integracoes"
PROXY = "/integracao/granatech/api-consignado/v1"
CPF = "52998224725"
CLIENTE = {"cpf": CPF, "nome": "Ana Teste", "telefone": "11999990000"}
SIMULACAO = {"id_margem": "m-1", "numero_parcelas": 36, "valor_parcela": "300", "idade": 30}


@pytest.fixture
def api(
    client_pg: TestClient, http_granatech: TestClient, fabrica: sessionmaker[Session]
) -> TestClient:
    return _com_granatech(client_pg, http_granatech, fabrica)


def _com_granatech(
    client_pg: TestClient, http: httpx.Client, fabrica: sessionmaker[Session], **extras: Any
) -> TestClient:
    opcoes = {"granatech_proposta_ativa": True, "granatech_dados_bancarios_ativo": True, **extras}
    cliente = ClienteGranatech(http, settings_granatech(**opcoes), fabrica, dormir=lambda _s: None)
    client_pg.app.dependency_overrides[get_granatech] = lambda: cliente  # type: ignore[attr-defined]
    client_pg.app.state.settings = settings_granatech(**opcoes)  # type: ignore[attr-defined]
    return client_pg


def _token(
    api: TestClient, fabrica: sessionmaker[Session], *escopos: str, nome: str = "APP MEX"
) -> dict[str, str]:
    csrf = entrar_como(api, fabrica, "gestor")
    criada = api.post(PAINEL, json={"nome": nome, "escopos": list(escopos)}, headers=csrf)
    assert criada.status_code == 201, criada.text
    api.cookies.clear()
    return {"Authorization": f"Bearer {criada.json()['token']}"}


def _abrir(api: TestClient, token: dict[str, str]) -> dict[str, Any]:
    resposta = api.get(f"{PROXY}/consulta-saldo", params=CLIENTE, headers=token)
    assert resposta.status_code == 200, resposta.text
    return dict(resposta.json())


def _simular(api: TestClient, token: dict[str, str], **extras: Any) -> httpx.Response:
    return api.get(f"{PROXY}/simulacao/p-1", params={**SIMULACAO, **extras}, headers=token)


def _corpo_proposta(id_consulta: str, simulacao: dict[str, Any]) -> dict[str, Any]:
    bloco = simulacao["resultado_da_simulacao_com_seguro"]
    return {
        "id_consulta": id_consulta,
        "id_produto": "p-1",
        "id_margem": "m-1",
        "informacoesFinanceira": [
            {
                "valor_solicitado": bloco["valor_solicitado"],
                "valor_parcela": bloco["valor_parcela"],
                "numero_parcelas": bloco["numero_parcelas"],
            }
        ],
        # O simulador só devolve o bloco com seguro.
        "informacaoDeSeguros": {"valor_seguro": bloco["valor_seguro"]},
    }


def _cota_usada(fabrica: sessionmaker[Session]) -> int:
    with abrir_sessao(fabrica) as sessao:
        return sum(sessao.scalars(select(Cota.usadas)).all())


# ------------------------------------------------------------------ consulta


def test_abre_consulta_com_dono_e_gasta_cota(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    consulta = _abrir(api, token)

    assert consulta["reaproveitada"] is False
    assert _cota_usada(fabrica) == 1
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(select(ConsultaGranatech)).one()
        assert linha.id_externo == consulta["id"]
        assert linha.integracao_id is not None and linha.conversa_id is None


def test_mesmo_cpf_reaproveita_sem_gastar_cota(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    primeira = _abrir(api, token)
    segunda = _abrir(api, token)
    assert segunda == {**primeira, "reaproveitada": True}
    assert _cota_usada(fabrica) == 1


def test_sem_cota_429_sem_chamar(
    client_pg: TestClient, http_granatech: TestClient, fabrica: Any, simulador_granatech: Any
) -> None:
    api = _com_granatech(client_pg, http_granatech, fabrica, granatech_cota_diaria=0)
    token = _token(api, fabrica, "operacoes")
    simulador_granatech.CHAMADAS.clear()
    resposta = api.get(f"{PROXY}/consulta-saldo", params=CLIENTE, headers=token)
    assert resposta.status_code == 429
    assert not any(r.endswith("/consulta-saldo") for _m, r in simulador_granatech.CHAMADAS)


def test_consulta_recente_de_outro_dono_nao_volta(api: TestClient, fabrica: Any) -> None:
    # Aberta por outro canal (aqui, sem dono): o APP MEX não a recebe.
    with abrir_sessao(fabrica) as sessao:
        sessao.add(ConsultaGranatech(id_externo="c-outro", cpf=CPF, status="PENDING"))
    token = _token(api, fabrica, "operacoes")
    resposta = api.get(f"{PROXY}/consulta-saldo", params=CLIENTE, headers=token)
    assert resposta.status_code == 409


def test_consulta_sem_id_volta_422_com_o_corpo(
    client_pg: TestClient,
    http_granatech: TestClient,
    fabrica: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Visto em produção: a Granatech responde 200 sem abrir a consulta.
    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.url.path.endswith("/consulta-saldo"):
            return httpx.Response(200, json={"cpf": CPF, "mensagem": "recusado"})
        resposta = http_granatech.request(
            pedido.method, pedido.url.path, content=pedido.content, headers=dict(pedido.headers)
        )
        return httpx.Response(
            resposta.status_code, content=resposta.content, headers=resposta.headers
        )

    http = httpx.Client(transport=httpx.MockTransport(responder), base_url="http://granatech")
    api = _com_granatech(client_pg, http, fabrica)
    token = _token(api, fabrica, "operacoes")

    resposta = api.get(f"{PROXY}/consulta-saldo", params=CLIENTE, headers=token)

    assert resposta.status_code == 422
    assert CPF not in resposta.text and "mensagem" in resposta.json()
    assert _cota_usada(fabrica) == 1  # a cota fica gasta (decisão do gestor)
    assert "granatech_consulta_sem_id chaves=['cpf', 'mensagem']" in caplog.text
    assert CPF not in caplog.text


def test_cpf_e_telefone_validados(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    ruim = {**CLIENTE, "cpf": "123"}
    assert api.get(f"{PROXY}/consulta-saldo", params=ruim, headers=token).status_code == 422


def test_escopo_operacoes_exigido(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "leitura")
    resposta = api.get(f"{PROXY}/consulta-saldo", params=CLIENTE, headers=token)
    assert resposta.status_code == 403


def test_termo_so_na_consulta_da_integracao(api: TestClient, fabrica: Any) -> None:
    dona = _token(api, fabrica, "operacoes")
    consulta = _abrir(api, dona)
    outra = _token(api, fabrica, "operacoes", nome="Outro sistema")
    corpo = {**CLIENTE, "email": "ana@exemplo.test", "id_consulta": consulta["id"]}

    assert api.post(f"{PROXY}/termo-consentimento", json=corpo, headers=outra).status_code == 409
    assert api.post(f"{PROXY}/termo-consentimento", json=corpo, headers=dona).status_code == 200


# ------------------------------------------------------------------ simulação e teto


def test_simulacao_dentro_do_teto_e_guardada(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    resposta = _simular(api, token)
    assert resposta.status_code == 200
    with abrir_sessao(fabrica) as sessao:
        (guardada,) = sessao.scalars(select(SimulacaoIntegracao)).all()
        assert guardada.id_margem == "m-1" and guardada.numero_parcelas == 36


def test_simulacao_acima_do_teto_nao_e_apresentada(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    # 500 × 36 no simulador libera ~R$ 7.699, acima do teto.
    resposta = _simular(api, token, valor_parcela="500")
    assert resposta.status_code == 422
    assert "resultado_da_simulacao_com_seguro" not in resposta.text
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(SimulacaoIntegracao)).all() == []


# ------------------------------------------------------------------ proposta


def _ate_simulacao(api: TestClient, fabrica: Any) -> tuple[dict[str, str], dict[str, Any]]:
    token = _token(api, fabrica, "operacoes", "acoes")
    consulta = _abrir(api, token)
    simulacao = _simular(api, token).json()
    return token, _corpo_proposta(consulta["id"], simulacao)


def test_proposta_criada_uma_vez(api: TestClient, fabrica: Any, simulador_granatech: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)

    primeira = api.post(f"{PROXY}/propostas", json=corpo, headers=token)
    segunda = api.post(f"{PROXY}/propostas", json=corpo, headers=token)

    assert primeira.status_code == 200, primeira.text
    assert segunda.json() == {"id": primeira.json()["id"], "reaproveitada": True}
    posts = [
        c for c in simulador_granatech.CHAMADAS if c[0] == "POST" and c[1].endswith("/propostas")
    ]
    assert len(posts) == 1
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(PropostaGranatech.integracao_id)).one() is not None


def test_proposta_sem_simulacao_igual_recusada(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    corpo["informacoesFinanceira"][0]["valor_solicitado"] = 5000.0
    resposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token)
    assert resposta.status_code == 422


def test_proposta_acima_do_teto_recusada(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    corpo["informacoesFinanceira"][0]["valor_solicitado"] = 7500.0
    resposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token)
    assert resposta.status_code == 422
    assert "teto" in resposta.json()["detail"]


def test_proposta_com_flag_desligada_503(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    api.app.state.settings = settings_granatech(granatech_proposta_ativa=False)  # type: ignore[attr-defined]
    assert api.post(f"{PROXY}/propostas", json=corpo, headers=token).status_code == 503


def test_cancelar_so_a_propria(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    id_proposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token).json()["id"]
    outra = _token(api, fabrica, "acoes", nome="Outro sistema")

    rota = f"{PROXY}/propostas/{id_proposta}/cancelar"
    assert api.post(rota, json={}, headers=outra).status_code == 409
    assert api.post(rota, json={}, headers=token).status_code == 200


def test_proposta_de_conversa_do_agente_e_intocavel(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    id_proposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token).json()["id"]
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(update(PropostaGranatech).values(integracao_id=None))
    rota = f"{PROXY}/propostas/{id_proposta}/cancelar"
    assert api.post(rota, json={}, headers=token).status_code == 409


def test_aviso_de_status_sai_para_a_dona(api: TestClient, fabrica: Any) -> None:
    # Ponta a ponta com a fase 2: a proposta do proxy muda de status e vira aviso.
    token, corpo = _ate_simulacao(api, fabrica)
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(
            update(Integracao).values(webhook_url="https://app.mex.test/a", webhook_segredo="s")
        )
    id_proposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token).json()["id"]
    jobs.aplicar(
        fabrica,
        None,
        {"tipo": "proposta", "id_proposta": id_proposta, "status": "PENDING_FORMALIZATION"},
    )
    with abrir_sessao(fabrica) as sessao:
        (aviso,) = sessao.scalars(select(Outbox)).all()
        assert aviso.payload["evento"]["id_proposta"] == id_proposta


# ------------------------------------------------------------------ incerto


def test_proposta_incerta_responde_202_sem_repetir(
    client_pg: TestClient, http_granatech: TestClient, fabrica: Any
) -> None:
    posts: list[str] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedido.method == "POST" and pedido.url.path.endswith("/propostas"):
            posts.append(pedido.url.path)
            raise httpx.ReadTimeout("sem resposta", request=pedido)
        if pedido.url.path.endswith("/propostas/lista"):
            return httpx.Response(200, json={"dados": []})
        # O resto (login, consulta, simulação) vai ao simulador.
        resposta = http_granatech.request(
            pedido.method,
            pedido.url.path,
            params=pedido.url.params,
            content=pedido.content,
            headers=dict(pedido.headers),
        )
        return httpx.Response(
            resposta.status_code, content=resposta.content, headers=resposta.headers
        )

    http = httpx.Client(transport=httpx.MockTransport(responder), base_url="http://granatech")
    api = _com_granatech(client_pg, http, fabrica)
    token, corpo = _ate_simulacao(api, fabrica)

    resposta = api.post(f"{PROXY}/propostas", json=corpo, headers=token)
    assert resposta.status_code == 202
    assert resposta.json()["situacao"] == "incerta"
    de_novo = api.post(f"{PROXY}/propostas", json=corpo, headers=token)
    assert de_novo.status_code == 202
    assert len(posts) == 1  # a segunda só procurou na listagem
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(PropostaGranatech.estado_envio)).one() == "incerta"


# ------------------------------------------------------------------ revisão da fase 3


@pytest.mark.parametrize(
    "estragar",
    [
        lambda c: c["informacoesFinanceira"].append(dict(c["informacoesFinanceira"][0])),
        lambda c: c["informacoesFinanceira"][0].update(numero_parcelas=True),
        lambda c: c["informacoesFinanceira"][0].update(valor_parcela="abc"),
        lambda c: c.update(informacoesFinanceira={"valor_parcela": 300}),
    ],
    ids=["dois_itens", "prazo_bool", "parcela_texto", "nao_e_lista"],
)
def test_corpo_malformado_422(api: TestClient, fabrica: Any, estragar: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    estragar(corpo)
    assert api.post(f"{PROXY}/propostas", json=corpo, headers=token).status_code == 422


def test_prazo_como_texto_de_digitos_vale(api: TestClient, fabrica: Any) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    corpo["informacoesFinanceira"][0]["numero_parcelas"] = "36"
    assert api.post(f"{PROXY}/propostas", json=corpo, headers=token).status_code == 200


def test_proposta_sem_seguro_nao_casa_com_simulacao_com_seguro(
    api: TestClient, fabrica: Any
) -> None:
    token, corpo = _ate_simulacao(api, fabrica)
    del corpo["informacaoDeSeguros"]
    assert api.post(f"{PROXY}/propostas", json=corpo, headers=token).status_code == 422


def test_termo_com_outro_cpf_recusado(api: TestClient, fabrica: Any) -> None:
    token = _token(api, fabrica, "operacoes")
    consulta = _abrir(api, token)
    corpo = {
        **CLIENTE,
        "cpf": "11144477735",
        "email": "a@exemplo.test",
        "id_consulta": consulta["id"],
    }
    assert api.post(f"{PROXY}/termo-consentimento", json=corpo, headers=token).status_code == 422


def test_dois_pedidos_ao_mesmo_tempo_um_post_so(
    api: TestClient, fabrica: Any, simulador_granatech: Any
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    token, corpo = _ate_simulacao(api, fabrica)
    with abrir_sessao(fabrica) as sessao:
        consulta_id = sessao.scalars(select(ConsultaGranatech.id)).one()
    cliente = api.app.dependency_overrides[get_granatech]()  # type: ignore[attr-defined]
    simulador_granatech.CHAMADAS.clear()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                lambda _i: cliente.criar_proposta(consulta_id=consulta_id, corpo=corpo), range(2)
            )
        )

    assert ids[0] == ids[1]
    posts = [
        c for c in simulador_granatech.CHAMADAS if c[0] == "POST" and c[1].endswith("/propostas")
    ]
    assert len(posts) == 1


def test_agente_ve_o_dono_da_consulta_do_app_mex(api: TestClient, fabrica: Any) -> None:
    # O nó do agente faz handoff quando a consulta reaproveitada tem integração dona.
    token = _token(api, fabrica, "operacoes")
    _abrir(api, token)
    cliente = api.app.dependency_overrides[get_granatech]()  # type: ignore[attr-defined]
    aberta = cliente.abrir_consulta(CPF, "Ana Teste", "11999990000")
    assert aberta.reaproveitada and aberta.integracao_id is not None
