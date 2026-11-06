"""Serviço que executa um turno de conversa."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage

from saturday.agent.context import AgentContext
from saturday.agent.state import turno_inicial
from saturday.agent.textos import mensagem_handoff
from saturday.metrics import TurnMetrics, iniciar_metricas, metricas_atuais
from saturday.schemas import AgentReply, ChatRequest
from saturday.services.webhook import WebhookClient
from saturday.settings import TZ_OPERACAO, Settings

logger = logging.getLogger(__name__)

StatusReply = Literal["answered", "handoff", "with_human", "duplicate"]


def agora() -> datetime:
    """Relógio do serviço; os testes podem substituir esta função."""

    return datetime.now(ZoneInfo(TZ_OPERACAO))


class AgentService:
    """Orquestra o grafo, o webhook, o checkpointer e os locks."""

    def __init__(
        self,
        graph: Any,
        context: AgentContext,
        webhook: WebhookClient,
        settings: Settings,
        checkpointer: Any = None,
    ) -> None:
        self.graph = graph
        self.context = context
        self.webhook = webhook
        self.settings = settings
        self.checkpointer = checkpointer
        self.locks = [threading.Lock() for _ in range(256)]

    def config(self, conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

    def estado_atual(self, config: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.graph.get_state(config)
        return dict(snapshot.values or {})

    def _lock(self, conversation_id: str) -> threading.Lock:
        digest = hashlib.blake2b(conversation_id.encode(), digest_size=8).digest()
        return self.locks[int.from_bytes(digest, "big") % len(self.locks)]

    def evento(
        self,
        conversation_id: str,
        estado: dict[str, Any],
        *,
        status: str | None = None,
        answer: str | None = None,
    ) -> AgentReply:
        status_estado = status or estado.get("status")
        if status_estado not in ("answered", "handoff", "with_human", "duplicate"):
            status_estado = "answered"
        return AgentReply(
            conversation_id=conversation_id,
            answer=answer if answer is not None else (estado.get("answer") or ""),
            status=cast(StatusReply, status_estado),
            intent=estado.get("intent"),
            publico=estado.get("publico"),
            handoff_reason=estado.get("handoff_reason"),
            portability_result=estado.get("portability_result"),
            timestamp=agora(),
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

    @staticmethod
    def _parse_iso(valor: Any) -> datetime | None:
        if not isinstance(valor, str) or not valor:
            return None
        try:
            data = datetime.fromisoformat(valor)
        except ValueError:
            return None
        if data.tzinfo is None:
            data = data.replace(tzinfo=ZoneInfo(TZ_OPERACAO))
        return data

    def _aplicar_retencao(
        self,
        config: dict[str, Any],
        estado: dict[str, Any],
    ) -> dict[str, Any]:
        recebido = self._parse_iso(estado.get("hiscon_recebido_em"))
        if recebido is None:
            return estado
        if agora() - recebido <= timedelta(days=self.settings.retencao_extrato_dias):
            return estado

        atualizacao = {
            "hiscon": None,
            "portability_result": None,
            "oferta_pendente": False,
            "hiscon_recebido_em": None,
        }
        self.graph.update_state(config, atualizacao)
        estado = dict(estado)
        estado.update(atualizacao)
        return estado

    @staticmethod
    def _atualizacao_liberacao() -> dict[str, Any]:
        return {
            "status": "in_progress",
            "handoff_reason": None,
            "oferta_pendente": False,
            "aguardando": None,
            "tentativas_coleta": 0,
            "tentativas_extrato": 0,
            "handoff_em": None,
        }

    def liberar(self, conversation_id: str) -> dict[str, Any] | None:
        """Devolve a conversa ao agente preservando histórico e dados."""

        config = self.config(conversation_id)
        estado = self.estado_atual(config)
        if not estado:
            return None
        self.graph.update_state(config, self._atualizacao_liberacao())
        return {"conversation_id": conversation_id, "status": "in_progress"}

    def _deve_liberar_auto(self, estado: dict[str, Any]) -> bool:
        if self.settings.handoff_auto_release_horas <= 0:
            return False
        if estado.get("status") != "handoff":
            return False
        em = self._parse_iso(estado.get("handoff_em"))
        if em is None:
            return False
        return agora() - em > timedelta(hours=self.settings.handoff_auto_release_horas)

    def _log_turno(
        self,
        conversation_id: str,
        estado: dict[str, Any],
        caminho: list[str],
        inicio: float,
        metricas: TurnMetrics | None,
    ) -> None:
        resumo = (
            metricas.resumo()
            if metricas
            else {
                "chamadas": [],
                "custo_total_usd": 0.0,
            }
        )
        extra: dict[str, Any] = {
            "conversation_id": conversation_id,
            "status": estado.get("status"),
            "handoff_reason": estado.get("handoff_reason"),
            "caminho": caminho,
            "latencia_total_ms": round((time.monotonic() - inicio) * 1000, 2),
            "chamadas": resumo["chamadas"],
            "custo_total_usd": resumo["custo_total_usd"],
        }
        resultado = estado.get("portability_result")
        if resultado is not None:
            extra["calculo_ok"] = resultado.get("ok")
            extra["contratos_elegiveis"] = sum(
                1 for contrato in resultado.get("contratos", []) if contrato.get("elegivel")
            )
        logger.info("turno", extra=extra)

    def _fallback_erro_interno(
        self,
        conversation_id: str,
        config: dict[str, Any],
        *,
        inicio: float,
        caminho: list[str],
        message_ids: list[str] | None,
    ) -> AgentReply:
        resposta = mensagem_handoff("erro_interno")
        atualizacao: dict[str, Any] = {
            "status": "handoff",
            "handoff_reason": "erro_interno",
            "answer": resposta,
            "handoff_em": agora().isoformat(),
            "messages": [AIMessage(content=resposta)],
        }
        if message_ids is not None:
            atualizacao["message_ids_recentes"] = message_ids[-50:]
        try:
            self.graph.update_state(config, atualizacao)
        except Exception:
            logger.exception(
                "falha_ao_gravar_erro_interno conversation_id=%s",
                conversation_id,
            )
        self._log_turno(
            conversation_id,
            atualizacao,
            caminho,
            inicio,
            metricas_atuais(),
        )
        return self.evento(conversation_id, atualizacao, status="handoff")

    def _processar_turno(self, payload: ChatRequest) -> AgentReply:
        config = self.config(payload.conversation_id)
        estado = self.estado_atual(config)
        estado = self._aplicar_retencao(config, estado)

        if estado.get("status") == "handoff":
            if not self._deve_liberar_auto(estado):
                return self.evento(
                    payload.conversation_id,
                    estado,
                    status="with_human",
                    answer="",
                )
            self.graph.update_state(config, self._atualizacao_liberacao())
            estado = self.estado_atual(config)

        ids_recentes = list(estado.get("message_ids_recentes") or [])
        if payload.message_id and payload.message_id in ids_recentes:
            return self.evento(
                payload.conversation_id,
                estado,
                status="duplicate",
                answer="",
            )

        cliente = self._cliente_mesclado(estado, payload)
        entrada = turno_inicial(
            user_message=payload.message,
            attachments=[a.model_dump(mode="json", exclude_none=True) for a in payload.attachments],
        )
        if cliente:
            entrada["cliente"] = cliente
        if payload.message_id:
            ids_recentes.append(payload.message_id)
            entrada["message_ids_recentes"] = ids_recentes[-50:]
        if payload.message.strip():
            entrada["messages"] = [HumanMessage(content=payload.message)]

        metricas = iniciar_metricas()
        inicio = time.monotonic()
        caminho: list[str] = []
        try:
            for atualizacao in self.graph.stream(
                entrada,
                config,
                context=self.context,
                stream_mode="updates",
            ):
                if isinstance(atualizacao, dict):
                    caminho.extend(
                        nome
                        for nome in atualizacao
                        if isinstance(nome, str) and not nome.startswith("__")
                    )
        except Exception:
            logger.exception(
                "erro_interno conversation_id=%s",
                payload.conversation_id,
            )
            return self._fallback_erro_interno(
                payload.conversation_id,
                config,
                inicio=inicio,
                caminho=caminho,
                message_ids=ids_recentes if payload.message_id else None,
            )

        final = dict(self.graph.get_state(config).values or {})
        self._log_turno(
            payload.conversation_id,
            final,
            caminho,
            inicio,
            metricas,
        )
        return self.evento(payload.conversation_id, final)

    def process_message(self, payload: ChatRequest) -> AgentReply:
        """Roda um turno inteiro sob a trava da conversa."""

        with self._lock(payload.conversation_id):
            return self._processar_turno(payload)

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
        if resposta.status in ("with_human", "duplicate"):
            # Não envia nada: a conversa está congelada ou o evento é repetido.
            return
        self.webhook.enviar(resposta.model_dump(mode="json"))
