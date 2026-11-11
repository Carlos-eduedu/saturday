"""Fixtures compartilhadas: app com serviços falsos, sem rede."""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.dados.base import Base
from saturday.dados.sessao import criar_factory
from saturday.services.anexos import Anexo
from saturday.services.jev import JevResult
from saturday.services.llm import LLMAnswer
from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage
from saturday.web.application import get_app
from saturday.web.dependencies import get_agent_service


def resultado_jev(
    intent: str = "duvida",
    conf: float = 0.9,
    publico: str = "inss",
    resposta_oferta: str | None = None,
    resposta_conf: float = 0.0,
    probabilities: dict[str, dict[str, float]] | None = None,
) -> JevResult:
    if probabilities is None:
        probabilities = {
            "intent": {
                "duvida": 0.9 if intent == "duvida" else 0.0,
                "suporte": 0.0,
                "humano": 0.9 if intent == "humano" else 0.0,
            },
            "publico": {publico: 0.9},
        }
        if resposta_oferta is not None:
            probabilities["resposta_oferta"] = {
                "aceita": 0.9 if resposta_oferta == "aceita" else 0.0,
                "recusa": 0.9 if resposta_oferta == "recusa" else 0.0,
                "duvida": 0.9 if resposta_oferta == "duvida" else 0.0,
            }
    return JevResult(
        intent=intent,
        intent_confidence=conf,
        publico=publico,
        publico_confidence=0.9,
        resposta_oferta=resposta_oferta,
        resposta_oferta_confidence=resposta_conf,
        probabilities=probabilities,
    )


def resposta_llm(
    resposta: str = "Sim, atendemos INSS.",
    resolvido: bool = True,
) -> LLMAnswer:
    return LLMAnswer(resposta=resposta, resolvido=resolvido)


class FakeJev:
    def __init__(self) -> None:
        self.resultado = resultado_jev()
        self.erro: Exception | None = None
        self.chamadas: list[tuple[str, bool]] = []
        self.ofertas: list[str | None] = []

    def classify(
        self,
        message: str,
        oferta_pendente: bool = False,
        oferta: str | None = None,
    ) -> JevResult:
        self.chamadas.append((message, oferta_pendente))
        self.ofertas.append(oferta)
        if self.erro is not None:
            raise self.erro
        return self.resultado


class FakeLLM:
    def __init__(self) -> None:
        self.resposta = resposta_llm()
        self.erro: Exception | None = None
        self.extrato: dict[str, Any] = {}
        self.chamadas_responder: list[tuple[list[dict[str, str]], str | None]] = []
        self.chamadas_extrato: list[list[Anexo]] = []

    def responder(
        self,
        historico: list[dict[str, str]],
        resumo: str | None = None,
    ) -> LLMAnswer:
        self.chamadas_responder.append((historico, resumo))
        if self.erro is not None:
            raise self.erro
        return self.resposta

    def ler_extrato(self, anexos: list[Anexo]) -> dict[str, Any]:
        self.chamadas_extrato.append(anexos)
        if self.erro is not None:
            raise self.erro
        return self.extrato


class FakeAnexos:
    def __init__(self) -> None:
        self.erro: Exception | None = None
        self.recebidos: list[dict[str, Any]] = []

    def carregar_anexos(self, itens: list[dict[str, Any]]) -> list[Anexo]:
        self.recebidos.extend(itens)
        if self.erro is not None:
            raise self.erro
        return [Anexo(mime_type="application/pdf", data=b"%PDF-1.7 fake")]

    def mensagem_anexo_invalido(self) -> str:
        return "Não consegui abrir esse arquivo."


class FakeWebhook:
    def __init__(self) -> None:
        self.configurado = False
        self.enviados: list[dict[str, Any]] = []
        self.erro: Exception | None = None

    def enviar(self, payload: dict[str, Any]) -> bool:
        if self.erro is not None:
            raise self.erro
        self.enviados.append(payload)
        return True


@dataclass
class Fakes:
    jev: FakeJev = field(default_factory=FakeJev)
    llm: FakeLLM = field(default_factory=FakeLLM)
    anexos: FakeAnexos = field(default_factory=FakeAnexos)
    webhook: FakeWebhook = field(default_factory=FakeWebhook)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="pytest",
        openrouter_api_key=SecretStr(""),
        llm_model="",
        vision_model="",
        whatsapp_token=SecretStr("token-de-teste"),
        whatsapp_app_secret=SecretStr("segredo-de-teste"),
        whatsapp_verify_token=SecretStr("verificacao-de-teste"),
        whatsapp_numeros=["100000000000001"],
    )


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def service(settings: Settings, fakes: Fakes) -> AgentService:
    # Os fakes duplicam a interface dos clientes sem herdar deles de propósito:
    # herdar traria a implementação real (rede) junto com a assinatura.
    context = AgentContext(jev=fakes.jev, llm=fakes.llm, anexos=fakes.anexos)  # type: ignore[arg-type]
    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer)
    agent_service = AgentService(
        graph=graph,
        context=context,
        webhook=fakes.webhook,  # type: ignore[arg-type]
        settings=settings,
        checkpointer=checkpointer,
    )
    return agent_service


@pytest.fixture
def conversa() -> str:
    """Id único por teste: as tabelas de checkpoint do Postgres não são limpas."""

    return f"teste-{uuid.uuid4().hex[:12]}"


def _montar_app(
    settings: Settings,
    service: AgentService,
    fabrica: Any = None,
) -> Any:
    application = get_app(settings)
    application.dependency_overrides[get_agent_service] = lambda: service
    application.state.agent_service = service
    # O webhook grava no banco; em `pytest` sem Postgres a fábrica fica nula.
    application.state.fabrica = fabrica
    return application


@pytest.fixture
def app(settings: Settings, service: AgentService) -> Any:
    return _montar_app(settings, service)


# ------------------------------------------------------------------ Postgres
#
# Os testes que dependem do backend real de estado (trava consultiva, poda de
# checkpoints, sobrevivência ao restart) rodam contra Postgres. Sem
# `SATURDAY_TEST_DATABASE_URL` eles são pulados, nunca reprovados por engano.


def _url_sqlalchemy(url: str) -> str:
    """SQLAlchemy precisa do dialeto explícito para o psycopg 3."""

    if url.startswith("postgresql+psycopg://"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.environ.get("SATURDAY_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip(
            "SATURDAY_TEST_DATABASE_URL não definida: este teste exige Postgres. "
            "Suba com `docker compose --profile postgres up -d postgres` e exporte a URL."
        )
    # Os fixtures abaixo rodam `drop_all`: apontar isso para um banco real
    # apagaria tudo. O nome do banco precisa marcar que é descartável.
    banco = urlsplit(url).path.lstrip("/")
    if "test" not in banco.lower():
        pytest.fail(
            f"SATURDAY_TEST_DATABASE_URL aponta para {banco!r}, que não é banco de teste. "
            "Os testes apagam e recriam as tabelas: use algo como saturday_test."
        )
    return url


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_engine(_url_sqlalchemy(pg_url), poolclass=NullPool, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def fabrica(pg_engine: Engine) -> sessionmaker[Session]:
    """Schema recriado antes de cada teste que usa banco."""

    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    return criar_factory(pg_engine)


@pytest.fixture
def checkpointer_pg(pg_url: str) -> Iterator[PostgresSaver]:
    pool = ConnectionPool(
        conninfo=pg_url,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    saver = PostgresSaver(pool)  # type: ignore[arg-type]
    saver.setup()
    yield saver
    pool.close()


@pytest.fixture
def storage() -> MemoriaStorage:
    """Storage em memória, para conferir o que a retenção apagou."""

    return MemoriaStorage()


def _servico_com_banco(
    settings: Settings,
    fakes: Fakes,
    checkpointer: Any,
    fabrica: sessionmaker[Session],
    storage: MemoriaStorage,
) -> AgentService:
    contexto = AgentContext(jev=fakes.jev, llm=fakes.llm, anexos=fakes.anexos)  # type: ignore[arg-type]
    return AgentService(
        graph=build_graph(checkpointer),
        context=contexto,
        webhook=fakes.webhook,  # type: ignore[arg-type]
        settings=settings,
        checkpointer=checkpointer,
        fabrica=fabrica,
        storage=storage,
    )


@pytest.fixture
def service_pg(
    settings: Settings,
    fakes: Fakes,
    checkpointer_pg: PostgresSaver,
    fabrica: sessionmaker[Session],
    storage: MemoriaStorage,
) -> AgentService:
    return _servico_com_banco(settings, fakes, checkpointer_pg, fabrica, storage)


@pytest.fixture
def client_pg(
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
) -> TestClient:
    return TestClient(_montar_app(settings, service_pg, fabrica))


@pytest.fixture
def client(app) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(app)


def extrato_fake() -> dict[str, Any]:
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    ano_ref, mes_ref = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    indice = ano_ref * 12 + (mes_ref - 1) - 22
    inicio = f"{indice % 12 + 1:02d}/{indice // 12}"
    return {
        "ehHiscon": True,
        "especie": "32",
        "liberadoParaEmprestimo": True,
        "dataEmissao": date(hoje.year, hoje.month, 1).strftime("%d/%m/%Y"),
        "margemUtilizada": 295.24,
        "margemDisponivel": 100.0,
        "margemReservada": 0.0,
        "margemExtrapolada": 0.0,
        "contratos": [
            {
                "banco": "643 - PINE",
                "situacao": "Ativo",
                "parcela": 295.24,
                "taxaMensal": 1.66,
                "qtdParcelas": 84,
                "inicioDesconto": inicio,
                "dataInclusao": "01/01/2020",
            }
        ],
    }


def anexo_fake() -> dict[str, str]:
    import base64

    return {
        "base64": base64.b64encode(b"%PDF-1.7 extrato").decode(),
        "mime_type": "application/pdf",
    }


# ------------------------------------------------------------------ simulador da Granatech
#
# O simulador mora fora do pacote (`simuladores/granatech/app.py`) e roda aqui
# em processo, pelo `TestClient`, que já é um `httpx.Client`: o cliente do
# Saturday fala com ele exatamente como falaria pela rede.

_RAIZ = Path(__file__).resolve().parents[3]


def _carregar_simulador_granatech() -> ModuleType:
    nome = "simulador_granatech"
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(
        nome, _RAIZ / "simuladores" / "granatech" / "app.py"
    )
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def simulador_granatech() -> Iterator[ModuleType]:
    modulo = _carregar_simulador_granatech()
    modulo.limpar()
    original = dict(modulo.CONFIG)
    modulo.CONFIG.update(atraso_detalhe_s=0, expira_em="1h")
    yield modulo
    modulo.CONFIG.clear()
    modulo.CONFIG.update(original)
    modulo.limpar()


@pytest.fixture
def http_granatech(simulador_granatech: ModuleType) -> Iterator[TestClient]:
    with TestClient(simulador_granatech.app, base_url="http://granatech") as cliente:
        yield cliente


def settings_granatech(**extras: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "pytest",
        "granatech_ativo": True,
        "granatech_base_url": "http://granatech",
        "granatech_chave_api": SecretStr("chave-do-simulador"),
        "granatech_webhook_token": SecretStr("token-do-simulador"),
    }
    base.update(extras)
    return Settings(**base)
