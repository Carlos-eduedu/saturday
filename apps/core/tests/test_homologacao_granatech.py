"""Homologação Granatech pelo painel (decisão 0014), contra o simulador."""

from __future__ import annotations

import functools
import io
import threading
import uuid
import zipfile
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from conftest import _montar_app, settings_granatech
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech.homologacao import Homologacao
from saturday.dados.modelos import Alerta, Auditoria, HomologacaoGranatech
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as jobs_granatech
from saturday.jobs import homologacao as jobs_homologacao
from saturday.painel import sessoes

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

CHAVE = "chave-do-simulador"
SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
ROTA = "/admin/granatech/homologacao"


def _homologacao(granatech: TestClient, eventos: dict[str, list[dict[str, Any]]]) -> Homologacao:
    return Homologacao(
        granatech=granatech,
        chave=CHAVE,
        ler_eventos=lambda id_externo: [{"payload": p} for p in eventos.get(id_externo, [])],
        espera_webhook_s=0,
        dormir=lambda _s: None,
    )


class _TodoId(dict[str, list[dict[str, Any]]]):
    """Webhook "recebido" para qualquer id."""

    def get(self, chave: str, padrao: Any = None) -> list[dict[str, Any]]:
        return [{"status": "SUCCESS", "id": chave}]


# ---------------------------------------------------------------- lógica (sem banco)


def test_fase1_gera_as_quatro_evidencias(http_granatech: TestClient) -> None:
    homologacao = _homologacao(http_granatech, _TodoId())

    assert homologacao.rodar(1) is None

    assert [(e.item, e.ok) for e in homologacao.evidencias] == [
        ("Consulta via resposta direta", True),
        ("Consulta via notificação do webhook", True),
        ("Simulação com seguro", True),
        ("Simulação sem seguro", True),
    ]
    # Na dev o "sem seguro" é ignorado; a evidência diz isso.
    assert "devolveu o bloco com seguro" in homologacao.evidencias[-1].observacao
    assert len(homologacao.ids_externos) == 1


def test_fase2_contrata_duas_vezes_e_registra_o_erro(
    http_granatech: TestClient, simulador_granatech: ModuleType
) -> None:
    homologacao = _homologacao(http_granatech, _TodoId())

    assert homologacao.rodar(2) is None

    assert [(e.item, e.ok) for e in homologacao.evidencias] == [
        ("Contratação 1 com sucesso", True),
        ("Contratação 2 com sucesso", True),
        ("Erro de contratação", True),
    ]
    assert len(simulador_granatech.PROPOSTAS) == 2
    assert all("dados_tomador" in p for p in simulador_granatech.PROPOSTAS.values())
    # 2 consultas e 2 propostas, para o worker não alertar nos webhooks.
    assert len(homologacao.ids_externos) == 4
    erro = homologacao.passos[-1]
    assert erro["arquivo"].endswith("-proposta-com-erro.json")
    assert 400 <= erro["status_http"] < 500

    texto = repr(homologacao.passos)
    assert CHAVE not in texto
    assert not any(token in texto for token in simulador_granatech.TOKENS)


def test_webhook_que_nao_chega_fica_registrado(http_granatech: TestClient) -> None:
    homologacao = _homologacao(http_granatech, {})

    assert homologacao.rodar(1) is None

    webhook = [e for e in homologacao.evidencias if "webhook" in e.item]
    assert webhook and not webhook[0].ok


def test_login_recusado_para_a_rodada(http_granatech: TestClient) -> None:
    homologacao = _homologacao(http_granatech, {})
    homologacao.chave = "chave-errada"

    erro = homologacao.rodar(1)

    assert erro is not None and "login recusado" in erro
    assert homologacao.evidencias == []


# ---------------------------------------------------------------- painel e worker (Postgres)


def _entrar(client: TestClient, fabrica: sessionmaker[Session], perfil: str) -> dict[str, str]:
    email = f"{perfil}-{uuid.uuid4().hex[:6]}@exemplo.test"
    with abrir_sessao(fabrica) as sessao:
        sessoes.criar_usuario(sessao, email, SENHA, perfil)
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200, resposta.text
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _painel(service: AgentService, fabrica: sessionmaker[Session], **extras: Any) -> TestClient:
    return TestClient(_montar_app(settings_granatech(**extras), service, fabrica))


@pytest.fixture
def rodadas(
    fabrica: sessionmaker[Session],
    simulador_granatech: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[jobs_homologacao.Rodadas]:
    """O executor do worker, falando com o simulador e sem esperas."""

    monkeypatch.setattr(
        jobs_homologacao.httpx,
        "Client",
        lambda **_kw: TestClient(simulador_granatech.app, base_url="http://granatech"),
    )
    monkeypatch.setattr(
        jobs_homologacao,
        "Homologacao",
        functools.partial(Homologacao, espera_webhook_s=0, intervalo_s=0),
    )
    parar = threading.Event()
    yield jobs_homologacao.Rodadas(fabrica, settings_granatech(), parar)
    parar.set()


def _esperar(rodadas: jobs_homologacao.Rodadas) -> None:
    assert rodadas.thread is not None
    rodadas.thread.join(timeout=30)
    assert not rodadas.thread.is_alive()


def test_gestor_pede_rodada_uma_por_vez_com_auditoria(
    service: AgentService, fabrica: sessionmaker[Session]
) -> None:
    # Com a URL inteira na variável, o https:// não sai dobrado.
    client = _painel(service, fabrica, dominio_publico="https://saturday.exemplo.test/")
    cabecalhos = _entrar(client, fabrica, "gestor")

    resposta = client.post(ROTA, json={"fase": 2}, headers=cabecalhos)
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["situacao"] == "pendente"
    assert client.post(ROTA, json={"fase": 1}, headers=cabecalhos).status_code == 409
    assert client.post(ROTA, json={"fase": 3}, headers=cabecalhos).status_code == 422

    lista = client.get(ROTA).json()
    assert lista["webhook_esperado"] == "https://saturday.exemplo.test/webhooks/granatech"
    assert [r["fase"] for r in lista["rodadas"]] == [2]
    assert lista["rodadas"][0]["pedido_por"]
    with abrir_sessao(fabrica) as sessao:
        acoes = sessao.scalars(select(Auditoria.acao)).all()
    assert "granatech:homologacao" in acoes


def test_atendente_nao_ve_nem_pede(service: AgentService, fabrica: sessionmaker[Session]) -> None:
    client = _painel(service, fabrica)
    cabecalhos = _entrar(client, fabrica, "atendente")

    assert client.get(ROTA).status_code == 403
    assert client.post(ROTA, json={"fase": 1}, headers=cabecalhos).status_code == 403


def test_indisponivel_com_a_granatech_de_producao(
    service: AgentService, fabrica: sessionmaker[Session]
) -> None:
    client = _painel(service, fabrica, granatech_base_url="https://api.granatech.com.br")
    cabecalhos = _entrar(client, fabrica, "gestor")

    assert client.get(ROTA).status_code == 404
    assert client.post(ROTA, json={"fase": 1}, headers=cabecalhos).status_code == 404


def test_worker_roda_a_rodada_e_o_zip_traz_o_relatorio(
    service: AgentService, fabrica: sessionmaker[Session], rodadas: jobs_homologacao.Rodadas
) -> None:
    client = _painel(service, fabrica)
    cabecalhos = _entrar(client, fabrica, "gestor")
    rodada_id = client.post(ROTA, json={"fase": 1}, headers=cabecalhos).json()["id"]

    assert rodadas.verificar() is True
    _esperar(rodadas)
    assert rodadas.verificar() is False

    detalhe = client.get(f"{ROTA}/{rodada_id}").json()
    # Sem webhook no teste: o item do webhook falha e a rodada também.
    assert detalhe["situacao"] == "falhou"
    assert detalhe["erro"] is None
    assert [i["ok"] for i in detalhe["itens"]] == [True, False, True, True]
    assert detalhe["passos"] and detalhe["terminado_em"]

    resposta = client.get(f"{ROTA}/{rodada_id}/zip")
    assert resposta.status_code == 200
    arquivos = zipfile.ZipFile(io.BytesIO(resposta.content))
    nomes = arquivos.namelist()
    assert "RELATORIO.md" in nomes
    assert len(nomes) == len(detalhe["passos"]) + 1
    assert "**falhou**" in arquivos.read("RELATORIO.md").decode()
    assert CHAVE not in resposta.content.decode("latin-1")


def test_webhook_de_id_da_homologacao_nao_alerta(
    fabrica: sessionmaker[Session],
) -> None:
    with abrir_sessao(fabrica) as sessao:
        sessao.add(HomologacaoGranatech(fase=1, situacao="concluida", ids_externos=["c-homolog"]))

    jobs_granatech._consulta(fabrica, None, {"id_solicitacao": "c-homolog", "status": "SUCCESS"})
    jobs_granatech._proposta(fabrica, {"id_proposta": "c-homolog", "status_da_proposta": "PAYED"})
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Alerta)) == 0

    jobs_granatech._consulta(fabrica, None, {"id_solicitacao": "outra", "status": "SUCCESS"})
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Alerta)) == 1


def test_rodada_em_andamento_vira_interrompida_quando_o_worker_sobe(
    fabrica: sessionmaker[Session],
) -> None:
    with abrir_sessao(fabrica) as sessao:
        sessao.add(HomologacaoGranatech(fase=1, situacao="em_andamento"))

    jobs_homologacao.Rodadas(fabrica, settings_granatech(), threading.Event())

    with abrir_sessao(fabrica) as sessao:
        rodada = sessao.scalars(select(HomologacaoGranatech)).one()
    assert rodada.situacao == "interrompida"
    assert rodada.terminado_em is not None
