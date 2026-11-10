"""Serviço que executa um turno de conversa."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.context import AgentContext
from saturday.agent.state import turno_inicial
from saturday.agent.textos import mensagem_handoff
from saturday.dados import repositorios
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import travar_conversa
from saturday.metrics import TurnMetrics, iniciar_metricas, metricas_atuais
from saturday.schemas import AgentReply, ChatRequest
from saturday.services.webhook import WebhookClient
from saturday.settings import TZ_OPERACAO, Settings
from saturday.storage.base import Storage

# Quantos pares mensagem/resposta ficam no checkpoint para idempotência.
JANELA_IDEMPOTENCIA = 50

logger = logging.getLogger(__name__)

StatusReply = Literal["answered", "handoff", "with_human", "duplicate"]


def agora() -> datetime:
    """Relógio do serviço; os testes podem substituir esta função."""

    return datetime.now(ZoneInfo(TZ_OPERACAO))


class AgentService:
    """Orquestra o grafo, o checkpointer, o outbox e a trava por conversa."""

    def __init__(
        self,
        graph: Any,
        context: AgentContext,
        webhook: WebhookClient,
        settings: Settings,
        checkpointer: Any = None,
        fabrica: sessionmaker[Session] | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.graph = graph
        self.context = context
        self.webhook = webhook
        self.settings = settings
        self.checkpointer = checkpointer
        # Sem `fabrica` (ambiente `pytest`) não há Postgres: o turno não grava
        # `mensagens` nem `outbox` e a entrega volta a ser direta. Em qualquer
        # outro ambiente `validar_para_subir` exige `SATURDAY_DATABASE_URL`.
        self.fabrica = fabrica
        self.storage = storage

    def config(self, conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

    def estado_atual(self, config: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.graph.get_state(config)
        return dict(snapshot.values or {})

    @contextmanager
    def _trava(self, conversation_id: str) -> Iterator[Session | None]:
        """Trava a conversa e mantém a transação aberta durante todo o turno.

        A trava é ``pg_advisory_xact_lock``: vale entre processos e some no
        commit. Devolve a sessão porque é dentro desta transação que a resposta
        vai para `mensagens` e para o `outbox`.
        """

        if self.fabrica is None:
            yield None
            return

        with abrir_sessao(self.fabrica) as aberta:
            travar_conversa(aberta, conversation_id)
            yield aberta

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

        self._apagar_anexos(estado.get("attachments") or [])
        atualizacao: dict[str, Any] = {
            "hiscon": None,
            "portability_result": None,
            "oferta_pendente": False,
            "hiscon_recebido_em": None,
            "attachments": [],
        }
        self.graph.update_state(config, atualizacao)
        self._podar_checkpoints(config)
        estado = dict(estado)
        estado.update(atualizacao)
        return estado

    def _apagar_anexos(self, anexos: list[dict[str, Any]]) -> None:
        """Apaga do storage os arquivos referenciados pelo estado."""

        if self.storage is None:
            return
        for anexo in anexos:
            chave = anexo.get("chave") if isinstance(anexo, dict) else None
            if chave:
                self.storage.apagar(str(chave))

    def _podar_checkpoints(self, config: dict[str, Any]) -> None:
        """Remove os checkpoints anteriores, que ainda contêm o extrato.

        Atualizar o estado só limpa o topo: os checkpoints antigos guardam os
        bytes do extrato. ``prune`` mantém apenas o checkpoint atual (já limpo).
        """

        thread_id = config["configurable"]["thread_id"]
        if hasattr(self.checkpointer, "prune"):
            self.checkpointer.prune([thread_id], strategy="keep_latest")
        elif hasattr(self.checkpointer, "delete_thread"):
            self.checkpointer.delete_thread(thread_id)

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
    ) -> AgentReply:
        resposta = mensagem_handoff("erro_interno")
        atualizacao: dict[str, Any] = {
            "status": "handoff",
            "handoff_reason": "erro_interno",
            "answer": resposta,
            "handoff_em": agora().isoformat(),
            "messages": [AIMessage(content=resposta)],
        }
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

    def _processar_turno(
        self,
        payload: ChatRequest,
        sessao: Session | None = None,
    ) -> AgentReply:
        config = self.config(payload.conversation_id)
        estado = self.estado_atual(config)
        estado = self._aplicar_retencao(config, estado)

        conversa = None
        if sessao is not None:
            conversa = repositorios.obter_ou_criar_conversa(sessao, payload.conversation_id)

        ids_recentes = list(estado.get("message_ids_recentes") or [])
        respostas = dict(estado.get("respostas_recentes") or {})
        if payload.message_id and payload.message_id in ids_recentes:
            # Devolve a mesma resposta já dada, não uma vazia.
            return self.evento(
                payload.conversation_id,
                estado,
                status="duplicate",
                answer=respostas.get(payload.message_id, ""),
            )

        if conversa is not None:
            repositorios.registrar_entrada(
                sessao,  # type: ignore[arg-type]
                conversa,
                message_id=payload.message_id,
                conteudo=payload.message,
            )

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

        cliente = self._cliente_mesclado(estado, payload)
        entrada = turno_inicial(
            user_message=payload.message,
            attachments=[a.model_dump(mode="json", exclude_none=True) for a in payload.attachments],
        )
        if cliente:
            entrada["cliente"] = cliente
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
            self._registrar_resposta(
                config,
                ids_recentes,
                respostas,
                payload.message_id,
                mensagem_handoff("erro_interno"),
            )
            return self._fallback_erro_interno(
                payload.conversation_id,
                config,
                inicio=inicio,
                caminho=caminho,
            )

        final = dict(self.graph.get_state(config).values or {})
        self._log_turno(
            payload.conversation_id,
            final,
            caminho,
            inicio,
            metricas,
        )
        resposta = self.evento(payload.conversation_id, final)

        if payload.message_id and resposta.answer:
            self._registrar_resposta(
                config, ids_recentes, respostas, payload.message_id, resposta.answer
            )
        if sessao is not None and conversa is not None:
            repositorios.registrar_saida(sessao, conversa, conteudo=resposta.answer or "")
            if self.webhook.configurado and resposta.status not in ("with_human", "duplicate"):
                enfileirar(
                    sessao,
                    conversa_id=conversa.id,
                    canal="webhook",
                    payload=resposta.model_dump(mode="json"),
                )
        return resposta

    def _registrar_resposta(
        self,
        config: dict[str, Any],
        ids_recentes: list[str],
        respostas: dict[str, str],
        message_id: str | None,
        answer: str,
    ) -> None:
        """Guarda o par mensagem/resposta no checkpoint para a idempotência."""

        if not message_id:
            return
        ids = [*ids_recentes, message_id][-JANELA_IDEMPOTENCIA:]
        recentes = {**respostas, message_id: answer}
        self.graph.update_state(
            config,
            {
                "message_ids_recentes": ids,
                "respostas_recentes": {
                    chave: texto for chave, texto in recentes.items() if chave in set(ids)
                },
            },
        )

    def process_message(self, payload: ChatRequest) -> AgentReply:
        """Roda um turno inteiro sob a trava da conversa."""

        with self._trava(payload.conversation_id) as sessao:
            return self._processar_turno(payload, sessao)

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
        if self.fabrica is not None:
            # Com Postgres a entrega é do worker, pelo `outbox` gravado no turno.
            return
        self.webhook.enviar(resposta.model_dump(mode="json"))
