"""Fixtures compartilhadas: app com serviços falsos, sem rede."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.services.anexos import Anexo
from saturday.services.jev import JevResult
from saturday.services.llm import LLMAnswer
from saturday.settings import Settings
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
        openrouter_api_key="",
        llm_model="",
        vision_model="",
    )


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def service(settings: Settings, fakes: Fakes) -> AgentService:
    context = AgentContext(jev=fakes.jev, llm=fakes.llm, anexos=fakes.anexos)
    checkpointer = InMemorySaver()
    graph = build_graph(checkpointer)
    agent_service = AgentService(
        graph=graph,
        context=context,
        webhook=fakes.webhook,
        settings=settings,
    )
    agent_service.checkpointer = checkpointer  # type: ignore[attr-defined]  # usado nos testes
    return agent_service


@pytest.fixture
def app(settings: Settings, service: AgentService):
    application = get_app(settings)
    application.dependency_overrides[get_agent_service] = lambda: service
    application.state.agent_service = service
    return application


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
