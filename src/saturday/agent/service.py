"""Serviço que executa um turno de conversa."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage

from saturday.agent.context import AgentContext
from saturday.agent.state import turno_inicial
from saturday.schemas import AgentReply, ChatRequest
from saturday.services.webhook import WebhookClient
from saturday.settings import TZ_OPERACAO, Settings

logger = logging.getLogger(__name__)


class AgentService:
    """Orquestra o grafo, o webhook e os recursos de uma instância."""

    def __init__(
        self,
        graph: Any,
        context: AgentContext,
        webhook: WebhookClient,
        settings: Settings,
    ) -> None:
        self.graph = graph
        self.context = context
        self.webhook = webhook
        self.settings = settings
        self.locks = [threading.Lock() for _ in range(256)]

    def config(self, conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

    def estado_atual(self, config: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.graph.get_state(config)
        return dict(snapshot.values or {})

    def evento(
        self,
        conversation_id: str,
        estado: dict[str, Any],
        *,
        status: str | None = None,
        answer: str | None = None,
    ) -> AgentReply:
        status_estado = status or estado.get("status")
        if status_estado not in ("answered", "handoff"):
            status_estado = "answered"
        return AgentReply(
            conversation_id=conversation_id,
            answer=answer if answer is not None else (estado.get("answer") or ""),
            status=status_estado,  # type: ignore[arg-type]  # validado acima
            intent=estado.get("intent"),
            publico=estado.get("publico"),
            handoff_reason=estado.get("handoff_reason"),
            portability_result=estado.get("portability_result"),
            timestamp=datetime.now(ZoneInfo(TZ_OPERACAO)),
        )

    def evento_atual(self, conversation_id: str) -> AgentReply:
        config = self.config(conversation_id)
        return self.evento(conversation_id, self.estado_atual(config))

    @staticmethod
    def _cliente_mesclado(estado: dict[str, Any], payload: ChatRequest) -> dict[str, Any]:
        cliente = dict(estado.get("cliente") or {})
        if payload.cliente is not None:
            for campo, valor in payload.cliente.model_dump(mode="json", exclude_none=True).items():
                cliente[campo] = valor
        return cliente

    def process_message(self, payload: ChatRequest) -> AgentReply | None:
        """Roda um turno. Devolve ``None`` se a conversa já está com um humano."""

        config = self.config(payload.conversation_id)
        estado = self.estado_atual(config)

        # Conversa em handoff fica congelada até um humano assumir.
        if estado.get("status") == "handoff":
            return None

        cliente = self._cliente_mesclado(estado, payload)
        entrada = turno_inicial(
            user_message=payload.message,
            attachments=[a.model_dump(exclude_none=True) for a in payload.attachments],
        )
        if cliente:
            entrada["cliente"] = cliente
        if payload.message.strip():
            entrada["messages"] = [HumanMessage(content=payload.message)]

        final = self.graph.invoke(entrada, config, context=self.context)
        resultado = final.get("portability_result") or {}
        logger.info(
            "turno conversation_id=%s status=%s motivo=%s calculo_ok=%s",
            payload.conversation_id,
            final.get("status"),
            final.get("handoff_reason"),
            resultado.get("ok"),
        )
        return self.evento(payload.conversation_id, final)

    def processar_e_enviar(self, payload: ChatRequest) -> None:
        try:
            resposta = self.process_message(payload)
        except Exception as exc:
            logger.error(
                "processamento_falhou conversation_id=%s erro=%s",
                payload.conversation_id,
                type(exc).__name__,
            )
            return
        if resposta is None:
            # Não envia nada: a conversa está com um atendente humano.
            return
        self.webhook.enviar(resposta.model_dump(mode="json"))
