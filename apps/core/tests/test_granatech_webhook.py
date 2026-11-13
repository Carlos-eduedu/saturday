"""Webhook da Granatech: autenticação, fila e aplicação dos eventos no worker."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest
from conftest import _montar_app, settings_granatech
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.dados.modelos import Alerta, ConsultaGranatech, EventoRecebido, PropostaGranatech
from saturday.jobs import alertas
from saturday.jobs import homologacao as jobs_homologacao
from saturday.jobs.eventos import processar
from saturday.settings import Settings

TOKEN = "token-do-simulador"  # noqa: S105 - token fixo do simulador, não é segredo
CPF = "00189004967"

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

EVENTO = {
    "id_solicitacao": "c1",
    "id_proposta": None,
    "cpf": CPF,
    "status": "PROCESSING",
    "user_id": 1,
    "corban_id": 1,
    "tipo": "CONSULTA",
}


def _api(service: AgentService, fabrica: Any = None, **extras: Any) -> TestClient:
    return TestClient(_montar_app(settings_granatech(**extras), service, fabrica))


# ------------------------------------------------------------------ autenticação (sem banco)


def test_sem_token_configurado_responde_503(service: AgentService) -> None:
    api = _api(service, granatech_webhook_token=SecretStr(""))

    resposta = api.post("/webhooks/granatech", json=EVENTO, headers={"x-webhook-token": ""})

    assert resposta.status_code == 503


def test_token_errado_responde_401(service: AgentService) -> None:
    resposta = _api(service).post(
        "/webhooks/granatech", json=EVENTO, headers={"x-webhook-token": "errado"}
    )

    assert resposta.status_code == 401


def test_recusa_registra_o_diagnostico_sem_o_token(
    service: AgentService, caplog: pytest.LogCaptureFixture
) -> None:
    """Token cru em Authorization (sem Bearer): 401, e o log diz o que mudar."""

    with caplog.at_level("WARNING", logger="saturday.web.api.granatech"):
        resposta = _api(service).post(
            "/webhooks/granatech?origem=dev",
            json=EVENTO,
            headers={"authorization": TOKEN, "user-agent": "granatech-webhook/1.0"},
        )

    assert resposta.status_code == 401
    [registro] = [r for r in caplog.records if r.getMessage() == "granatech_token_invalido"]
    campos = registro.__dict__
    assert campos["token_fontes"] == ["authorization_sem_bearer:cru"]
    assert campos["authorization_cru_bate"] is True
    assert campos["token_tamanho"] == 0
    assert campos["token_esperado_tamanho"] == len(TOKEN)
    assert campos["query_parametros"] == ["origem"]
    assert campos["corpo_tipo"] == "CONSULTA"
    assert "cpf" in campos["corpo_chaves"]
    assert campos["user_agent"] == "granatech-webhook/1.0"
    assert CPF not in repr(campos)
    assert TOKEN[:6] not in repr({k: v for k, v in campos.items() if k != "args"})


def test_token_com_espaco_aparece_no_diagnostico(
    service: AgentService, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger="saturday.web.api.granatech"):
        _api(service).post(
            "/webhooks/granatech", json=EVENTO, headers={"x-webhook-token": TOKEN + " "}
        )

    [registro] = [r for r in caplog.records if r.getMessage() == "granatech_token_invalido"]
    assert registro.__dict__["token_com_espacos"] is True
    assert registro.__dict__["token_bate_sem_espacos"] is True
    assert registro.__dict__["token_fontes"] == ["x-webhook-token"]


def test_sem_token_na_requisicao_responde_401(service: AgentService) -> None:
    assert _api(service).post("/webhooks/granatech", json=EVENTO).status_code == 401


@pytest.mark.parametrize(
    ("url", "cabecalhos"),
    [
        (f"/webhooks/granatech?t={TOKEN}", {}),
        ("/webhooks/granatech", {"authorization": f"Bearer {TOKEN}"}),
        ("/webhooks/granatech", {"x-webhook-token": TOKEN}),
    ],
)
def test_token_aceito_nas_tres_formas(
    service: AgentService, url: str, cabecalhos: dict[str, str]
) -> None:
    assert _api(service).post(url, json=EVENTO, headers=cabecalhos).status_code == 200


def test_corpo_que_nao_e_objeto_responde_400(service: AgentService) -> None:
    resposta = _api(service).post(
        "/webhooks/granatech", json=[1, 2], headers={"x-webhook-token": TOKEN}
    )

    assert resposta.status_code == 400


# ------------------------------------------------------------------ fila e worker (Postgres)


@pytest.fixture
def api_pg(service: AgentService, fabrica: sessionmaker[Session]) -> TestClient:
    return _api(service, fabrica)


@pytest.fixture
def cliente(http_granatech: TestClient, fabrica: sessionmaker[Session]) -> ClienteGranatech:
    return ClienteGranatech(
        http_granatech,
        settings_granatech(granatech_proposta_ativa=True),
        fabrica,
        dormir=lambda _: None,
    )


@pytest.fixture
def entregar(simulador_granatech: ModuleType, api_pg: TestClient) -> Iterator[list[int]]:
    """O simulador entrega os eventos na API em processo."""

    respostas: list[int] = []

    def para_api(evento: dict[str, Any]) -> int:
        resposta = api_pg.post(
            "/webhooks/granatech", json=evento, headers={"x-webhook-token": TOKEN}
        )
        respostas.append(resposta.status_code)
        return resposta.status_code

    original = simulador_granatech.entregar
    simulador_granatech.entregar = para_api
    yield respostas
    simulador_granatech.entregar = original


def _disparar(http_granatech: TestClient, **corpo: Any) -> None:
    assert http_granatech.post("/admin/evento", json=corpo).status_code == 200


def _rodar_worker(
    fabrica: sessionmaker[Session],
    service: AgentService,
    cliente: ClienteGranatech | None,
    settings: Settings,
) -> None:
    # A entrada do WhatsApp não é usada por eventos da Granatech.
    while processar(fabrica, service, None, settings, cliente):  # type: ignore[arg-type]
        pass


def _consulta(fabrica: sessionmaker[Session], id_externo: str) -> ConsultaGranatech:
    with fabrica() as sessao:
        return sessao.scalars(
            select(ConsultaGranatech).where(ConsultaGranatech.id_externo == id_externo)
        ).one()


def _alertas(fabrica: sessionmaker[Session]) -> list[dict[str, Any]]:
    with fabrica() as sessao:
        return [a.detalhe or {} for a in sessao.scalars(select(Alerta)).all()]


def test_evento_duplicado_vira_uma_linha(
    api_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    for _ in range(3):
        api_pg.post("/webhooks/granatech", json=EVENTO, headers={"x-webhook-token": TOKEN})
    # Mesma informação em outra ordem de chaves também é duplicado.
    api_pg.post(
        "/webhooks/granatech",
        json=dict(reversed(list(EVENTO.items()))),
        headers={"x-webhook-token": TOKEN},
    )

    with fabrica() as sessao:
        assert sessao.scalar(select(func.count(EventoRecebido.id))) == 1


def test_success_aplica_status_e_grava_o_detalhe(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    _disparar(http_granatech, tipo="consulta", id=aberta.id_externo, status="PROCESSING")
    _disparar(http_granatech, tipo="consulta", id=aberta.id_externo, status="SUCCESS")
    _rodar_worker(fabrica, service, cliente, settings)

    assert entregar == [200, 200]
    consulta = _consulta(fabrica, aberta.id_externo)
    assert consulta.status == "SUCCESS"
    assert consulta.detalhe is not None
    assert len(consulta.detalhe["margens"]) == 2
    assert [h["status"] for h in consulta.historico] == ["PROCESSING", "SUCCESS"]


def test_success_sem_cliente_so_atualiza_o_status(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    _disparar(http_granatech, tipo="consulta", id=aberta.id_externo, status="SUCCESS")
    _rodar_worker(fabrica, service, None, settings)

    consulta = _consulta(fabrica, aberta.id_externo)
    assert consulta.status == "SUCCESS"
    assert consulta.detalhe is None


@pytest.mark.parametrize(
    "status",
    [
        "AWAITING_CLIENT_AUTHORIZATION",
        "PROCESSING",
        "PENDING",
        "SUCCESS",
        "NO_MARGIN",
        "USED",
        "UNEXPECTED_ERROR",
        "FIDUCIARY_INSTITUTION_NO_AUTHORIZATION",
        "WORKER_MUST_CANCEL_RETURN_REQUEST",
    ],
)
def test_cada_status_de_consulta_e_aplicado(
    status: str,
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    _disparar(http_granatech, tipo="consulta", id=aberta.id_externo, status=status)
    _rodar_worker(fabrica, service, cliente, settings)

    assert _consulta(fabrica, aberta.id_externo).status == status
    atencao = {
        "UNEXPECTED_ERROR",
        "FIDUCIARY_INSTITUTION_NO_AUTHORIZATION",
        "WORKER_MUST_CANCEL_RETURN_REQUEST",
    }
    assert bool(_alertas(fabrica)) == (status in atencao)


def test_consulta_com_id_consulta_da_api_dev_e_aplicada(
    api_pg: TestClient,
    cliente: ClienteGranatech,
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    """Forma que a api-dev mandou no dev: `id_consulta` no lugar de `id_solicitacao`."""

    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    corpo = {"cpf": CPF, "id_consulta": aberta.id_externo, "status": "SUCCESS", "tipo": "CONSULTA"}

    resposta = api_pg.post("/webhooks/granatech", json=corpo, headers={"x-webhook-token": TOKEN})
    _rodar_worker(fabrica, service, cliente, settings)

    assert resposta.status_code == 200
    assert _consulta(fabrica, aberta.id_externo).status == "SUCCESS"
    assert _alertas(fabrica) == []
    with fabrica() as sessao:
        [evento] = jobs_homologacao.eventos_do_id(sessao, aberta.id_externo)
    assert evento["payload"]["status"] == "SUCCESS"


def test_consulta_concluida_em_portugues_e_aplicada(
    api_pg: TestClient,
    cliente: ClienteGranatech,
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    """A api-dev manda `CONCLUIDO` (worker do dev, 2026-11-13): vale `SUCCESS`, sem alerta."""

    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    corpo = {
        "cpf": CPF,
        "id_consulta": aberta.id_externo,
        "status": "CONCLUIDO",
        "tipo": "CONSULTA",
    }

    resposta = api_pg.post("/webhooks/granatech", json=corpo, headers={"x-webhook-token": TOKEN})
    _rodar_worker(fabrica, service, cliente, settings)

    assert resposta.status_code == 200
    assert _consulta(fabrica, aberta.id_externo).status == "SUCCESS"
    assert _alertas(fabrica) == []


def test_consulta_fora_de_ordem_nao_regride(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    _disparar(
        http_granatech,
        ordem="invertida",
        eventos=[
            {"tipo": "consulta", "id": aberta.id_externo, "status": "PROCESSING"},
            {"tipo": "consulta", "id": aberta.id_externo, "status": "SUCCESS", "repetir": 2},
        ],
    )
    _rodar_worker(fabrica, service, cliente, settings)

    consulta = _consulta(fabrica, aberta.id_externo)
    assert consulta.status == "SUCCESS"
    # O duplicado não entra; o atrasado entra no histórico, mas não muda o status.
    assert [h["status"] for h in consulta.historico] == ["SUCCESS", "PROCESSING"]


def test_status_e_consulta_desconhecidos_viram_alerta(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    _disparar(http_granatech, tipo="consulta", id=aberta.id_externo, status="STATUS_NOVO")
    _disparar(http_granatech, tipo="consulta", id="nao-existe", status="SUCCESS")
    _rodar_worker(fabrica, service, cliente, settings)

    motivos = sorted(a["motivo"] for a in _alertas(fabrica))
    assert motivos == ["consulta_desconhecida", "status_desconhecido"]
    assert _consulta(fabrica, aberta.id_externo).status == "AWAITING_CLIENT_AUTHORIZATION"
    assert all(CPF not in str(a) for a in _alertas(fabrica))


# ------------------------------------------------------------------ proposta


def _proposta_criada(cliente: ClienteGranatech) -> str:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    return cliente.criar_proposta(
        consulta_id=aberta.id_local,
        corpo={
            "id_consulta": aberta.id_externo,
            "informacoesFinanceira": [{"valor_parcela": 300.0, "numero_parcelas": 36}],
        },
    )


def _proposta(fabrica: sessionmaker[Session], id_externo: str) -> PropostaGranatech:
    with fabrica() as sessao:
        return sessao.scalars(
            select(PropostaGranatech).where(PropostaGranatech.id_externo == id_externo)
        ).one()


@pytest.mark.parametrize(
    ("status", "notificacao", "esperado"),
    [
        ("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO", "PENDING_CONFIRMATION"),
        ("PENDING_USER_REVIEW", "AGUARDANDO_REVISAO_USUARIO", "PENDING_USER_REVIEW"),
        ("PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO", "PENDING_FORMALIZATION"),
        ("PENDING_FORMALIZATION", "BLOQUEIO_SALDO", "PENDING_FORMALIZATION"),
        ("PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO", "PENDING_BANK_ANALYSIS"),
        ("PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE", "PENDING_PAYMENT"),
        ("PENDING_REFORMALIZATION", "REFAZER_SEGURANCA_IDENTIDADE", "PENDING_REFORMALIZATION"),
        ("REPROVED", "REPROVADO", "REPROVED"),
        ("CANCELED", "CANCELADO", "CANCELED"),
        ("PAYED", "PAGO", "PAYED"),
        ("PENDING_PAYMENT", "PROPOSTA_PAGA", "PAYED"),
    ],
)
def test_cada_status_de_proposta_e_aplicado(
    status: str,
    notificacao: str,
    esperado: str,
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    id_proposta = _proposta_criada(cliente)

    _disparar(
        http_granatech,
        tipo="proposta",
        id=id_proposta,
        status=status,
        tipo_notificacao=notificacao,
    )
    _rodar_worker(fabrica, service, cliente, settings)

    proposta = _proposta(fabrica, id_proposta)
    assert proposta.status == esperado
    assert proposta.tipo_notificacao == notificacao


@pytest.mark.parametrize(
    ("status_api_dev", "esperado"),
    [
        ("AGUARDANDO_CONFIRMACAO", "PENDING_CONFIRMATION"),
        ("AGUARDANDO_FORMALIZACAO", "PENDING_FORMALIZATION"),
        ("PAGO", "PAYED"),
    ],
)
def test_proposta_no_formato_da_api_dev_e_aplicada(
    status_api_dev: str,
    esperado: str,
    api_pg: TestClient,
    cliente: ClienteGranatech,
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    """Rodada 11: a api-dev manda a notificação em `status`, sem `tipo_notificacao`."""

    id_proposta = _proposta_criada(cliente)
    corpo = {"cpf": CPF, "tipo": "PROPOSTA", "status": status_api_dev, "id_proposta": id_proposta}

    resposta = api_pg.post("/webhooks/granatech", json=corpo, headers={"x-webhook-token": TOKEN})
    _rodar_worker(fabrica, service, cliente, settings)

    assert resposta.status_code == 200
    proposta = _proposta(fabrica, id_proposta)
    assert proposta.status == esperado
    assert proposta.tipo_notificacao == status_api_dev
    assert _alertas(fabrica) == []


def test_proposta_paga_nao_volta_atras(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    id_proposta = _proposta_criada(cliente)

    _disparar(
        http_granatech,
        ordem="invertida",
        eventos=[
            {"tipo": "proposta", "id": id_proposta, "status": "PENDING_FORMALIZATION"},
            {"tipo": "proposta", "id": id_proposta, "status": "PENDING_PAYMENT"},
            {"tipo": "proposta", "id": id_proposta, "status": "PAYED", "tipo_notificacao": "PAGO"},
        ],
    )
    _disparar(
        http_granatech,
        tipo="proposta",
        id=id_proposta,
        status="PENDING_USER_REVIEW",
        tipo_notificacao="FALHA_PAGAMENTO",
    )
    _rodar_worker(fabrica, service, cliente, settings)

    proposta = _proposta(fabrica, id_proposta)
    assert proposta.status == "PAYED"
    assert len(proposta.historico) == 4


def test_regressao_legitima_antes_do_final(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    id_proposta = _proposta_criada(cliente)

    _disparar(
        http_granatech,
        eventos=[
            {"tipo": "proposta", "id": id_proposta, "status": "PENDING_PAYMENT"},
            {
                "tipo": "proposta",
                "id": id_proposta,
                "status": "PENDING_USER_REVIEW",
                "tipo_notificacao": "FALHA_PAGAMENTO",
            },
        ],
    )
    _rodar_worker(fabrica, service, cliente, settings)

    assert _proposta(fabrica, id_proposta).status == "PENDING_USER_REVIEW"


def test_proposta_com_status_desconhecido_vira_alerta(
    cliente: ClienteGranatech,
    http_granatech: TestClient,
    entregar: list[int],
    fabrica: sessionmaker[Session],
    service: AgentService,
    settings: Settings,
) -> None:
    id_proposta = _proposta_criada(cliente)

    _disparar(http_granatech, tipo="proposta", id=id_proposta, status="NOVIDADE")
    _disparar(http_granatech, tipo="proposta", id="outra", status="PAYED")
    _rodar_worker(fabrica, service, cliente, settings)

    motivos = sorted(a["motivo"] for a in _alertas(fabrica))
    assert motivos == ["proposta_desconhecida", "status_desconhecido"]
    assert _proposta(fabrica, id_proposta).status is None


# ------------------------------------------------------------------ consulta parada


def _envelhecer(fabrica: sessionmaker[Session], minutos: int) -> None:
    with fabrica.begin() as sessao:
        sessao.execute(
            update(ConsultaGranatech).values(atualizada_em=func.now() - timedelta(minutes=minutos))
        )


def test_consulta_sem_evento_ha_15_min_gera_um_alerta_so(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    assert alertas.verificar(fabrica) == 0

    _envelhecer(fabrica, 16)
    alertas.verificar(fabrica)
    alertas.verificar(fabrica)

    assert _alertas(fabrica) == [
        {"consulta": aberta.id_externo, "status": "AWAITING_CLIENT_AUTHORIZATION"}
    ]


def test_consulta_final_parada_nao_gera_alerta(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    with fabrica.begin() as sessao:
        sessao.get_one(ConsultaGranatech, aberta.id_local).status = "SUCCESS"
    _envelhecer(fabrica, 60)

    assert alertas.verificar(fabrica) == 0
