"""Roda o grafo e fecha o turno: trilha, resposta, handoff e saída.

O turno de cliente e o turno de sistema passam pelo mesmo fechamento; o que os
separa está aqui, não em quem chama. O que vai para o banco passa pelo
`RegistroDoTurno`, que tem dois adapters: Postgres e memória (sem banco).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from saturday.agent.context import AgentContext
from saturday.agent.textos import chave_handoff, mensagem_handoff
from saturday.canais.base import CANAIS_WHATSAPP
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.outbox import enfileirar
from saturday.metrics import TurnMetrics, iniciar_metricas, metricas_atuais
from saturday.schemas import AgentReply
from saturday.services.webhook import WebhookClient

# O log do turno sempre saiu com o nome do serviço; filtros e painéis de log
# dependem dele.
logger = logging.getLogger("saturday.agent.service")


def etapa_do_estado(estado: dict[str, Any]) -> str | None:
    """Etapa CLT em curso; `inss` na jornada de portabilidade; senão nada."""

    clt = estado.get("clt")
    if isinstance(clt, dict) and clt.get("etapa"):
        return str(clt["etapa"])[:32]
    if estado.get("publico") == "inss" or estado.get("hiscon"):
        return "inss"
    return None


class RegistroDoTurno(Protocol):
    """O que o fechamento do turno grava fora do checkpoint."""

    @property
    def com_humano(self) -> bool: ...

    def registrar_turno(
        self,
        estado: dict[str, Any],
        caminho: list[str],
        metricas: TurnMetrics | None,
        inicio: float,
        erro: str | None = None,
    ) -> int | None: ...

    def abrir_handoff(
        self,
        tipo_alerta: str,
        motivo: str | None,
        detalhe: dict[str, Any] | None = None,
    ) -> None: ...

    def alertar_evento_com_humano(self, detalhe: dict[str, Any]) -> None: ...

    def gravar_saida(
        self,
        resposta: AgentReply,
        final: dict[str, Any] | None = None,
        *,
        turno_id: int | None = None,
    ) -> None: ...


class RegistroMemoria:
    """Sem Postgres (`pytest`): nada é gravado e a entrega volta a ser direta."""

    com_humano = False

    def registrar_turno(
        self,
        estado: dict[str, Any],
        caminho: list[str],
        metricas: TurnMetrics | None,
        inicio: float,
        erro: str | None = None,
    ) -> int | None:
        return None

    def abrir_handoff(
        self,
        tipo_alerta: str,
        motivo: str | None,
        detalhe: dict[str, Any] | None = None,
    ) -> None:
        return None

    def alertar_evento_com_humano(self, detalhe: dict[str, Any]) -> None:
        return None

    def gravar_saida(
        self,
        resposta: AgentReply,
        final: dict[str, Any] | None = None,
        *,
        turno_id: int | None = None,
    ) -> None:
        return None


@dataclass
class RegistroPostgres:
    """Grava na transação do turno, a mesma que segura a trava da conversa."""

    sessao: Session
    conversa: Conversa
    webhook: WebhookClient

    @property
    def com_humano(self) -> bool:
        return self.conversa.atendimento != "ia"

    def registrar_turno(
        self,
        estado: dict[str, Any],
        caminho: list[str],
        metricas: TurnMetrics | None,
        inicio: float,
        erro: str | None = None,
    ) -> int | None:
        """Etapa na conversa (para a lista) e a trilha do turno (abas "IA" e Agente).

        Só códigos, números e tempos: nenhum texto do cliente ou do modelo. O
        aviso `turno` atualiza ao vivo a lista de execuções do painel. Devolve o
        id do turno, que vai na mensagem de saída (procedência, decisão 0018).
        """

        conversa = self.conversa
        conversa.etapa = etapa_do_estado(estado)
        resumo = metricas.resumo() if metricas else {"chamadas": [], "custo_total_usd": 0.0}
        classificou = "classify_intent" in caminho
        turno = Turno(
            conversa_id=conversa.id,
            caminho=list(caminho),
            status=estado.get("status"),
            motivo=estado.get("handoff_reason"),
            etapa=conversa.etapa,
            classificacao=(
                {
                    "intencao": estado.get("intent"),
                    "publico": estado.get("publico"),
                    "confianca": estado.get("intent_confidence"),
                }
                if classificou
                else None
            ),
            chamadas=resumo["chamadas"],
            custo_usd=resumo["custo_total_usd"],
            tokens=resumo.get("tokens_total", 0),
            duracao_ms=round((time.monotonic() - inicio) * 1000),
            erro=erro,
        )
        self.sessao.add(turno)
        self.sessao.flush()
        repositorios.notificar(self.sessao, "turno", conversa=conversa.id)
        return turno.id

    def abrir_handoff(
        self,
        tipo_alerta: str,
        motivo: str | None,
        detalhe: dict[str, Any] | None = None,
    ) -> None:
        repositorios.mudar_atendimento(self.sessao, self.conversa, "handoff")
        repositorios.abrir_alerta(
            self.sessao,
            tipo_alerta,
            conversa_id=self.conversa.id,
            detalhe={"motivo": motivo, **(detalhe or {})},
            unico=True,
        )

    def alertar_evento_com_humano(self, detalhe: dict[str, Any]) -> None:
        repositorios.abrir_alerta(
            self.sessao,
            "evento_com_humano",
            conversa_id=self.conversa.id,
            detalhe=detalhe,
        )

    def gravar_saida(
        self,
        resposta: AgentReply,
        final: dict[str, Any] | None = None,
        *,
        turno_id: int | None = None,
    ) -> None:
        """Histórico da resposta e, quando houver canal, o envio no outbox.

        ``final`` (o estado do turno) pode pedir um modelo: ``modelo_envio`` sai
        sempre como modelo (marketing); ``modelo_aviso`` e ``link_aviso`` são o
        aviso usado se a janela de 24 h estiver fechada. ``turno_id`` e a
        ``chave_mensagem`` do estado dão a procedência da fala (decisão 0018).
        """

        conversa = self.conversa
        final = final or {}
        if final.get("marketing") in ("opt_in", "opt_out"):
            conversa.marketing = final["marketing"]
        modelo_envio = final.get("modelo_envio")
        conteudo = resposta.answer or (f"[modelo {modelo_envio}]" if modelo_envio else "")
        mensagem_id = repositorios.registrar_saida(
            self.sessao,
            conversa,
            conteudo=conteudo,
            turno_id=turno_id,
            chave_mensagem=final.get("chave_mensagem"),
        )
        canal = self._canal_de_saida(resposta)
        if canal is None:
            return
        # O id volta no payload: é nesta linha que o worker grava o `wamid` e o
        # status de entrega quando a Meta confirmar.
        payload = resposta.model_dump(mode="json")
        if canal in CANAIS_WHATSAPP:
            payload["numero"] = conversa.telefone
            payload["phone_number_id"] = conversa.phone_number_id
        payload["mensagem_id"] = mensagem_id
        if canal in CANAIS_WHATSAPP:
            for chave, destino in (
                ("modelo_envio", "modelo"),
                ("modelo_aviso", "modelo_aviso"),
                ("link_aviso", "link_aviso"),
            ):
                if final.get(chave):
                    payload[destino] = final[chave]
        enfileirar(self.sessao, conversa_id=conversa.id, canal=canal, payload=payload)

    def _canal_de_saida(self, resposta: AgentReply) -> str | None:
        """Quem entrega esta resposta.

        No WhatsApp (Meta ou Evolution) a resposta sempre passa pelo outbox, inclusive no handoff —
        o cliente precisa saber que a conversa foi para uma pessoa. No webhook,
        o handoff continua não gerando envio, como antes.
        """

        if resposta.status == "duplicate":
            return None
        if self.conversa.canal in CANAIS_WHATSAPP:
            return self.conversa.canal
        if self.webhook.configurado and resposta.status != "with_human":
            return "webhook"
        return None


class Turnos:
    """Roda um turno no grafo e o fecha, para o cliente ou para o sistema."""

    def __init__(
        self,
        graph: Any,
        context: AgentContext,
        evento: Callable[..., AgentReply],
        agora: Callable[[], datetime],
    ) -> None:
        self.graph = graph
        self.context = context
        self._evento = evento
        self._agora = agora

    def de_cliente(
        self,
        conversation_id: str,
        config: dict[str, Any],
        entrada: dict[str, Any],
        registro: RegistroDoTurno,
        *,
        estado: dict[str, Any],
        guardar_resposta: Callable[[str], None],
    ) -> AgentReply:
        """Turno com mensagem do cliente: a saída sempre é gravada.

        Se o grafo falhar, a conversa vai para handoff `erro_interno` e o cliente
        é avisado. ``estado`` é o de antes do turno; ``guardar_resposta`` guarda o
        par mensagem/resposta para a idempotência.
        """

        metricas = iniciar_metricas()
        inicio = time.monotonic()
        caminho: list[str] = []
        try:
            self._stream(entrada, config, caminho)
        except Exception as exc:
            logger.exception("erro_interno conversation_id=%s", conversation_id)
            turno_id = registro.registrar_turno(
                {**estado, "status": "handoff", "handoff_reason": "erro_interno"},
                caminho,
                metricas,
                inicio,
                erro=type(exc).__name__,
            )
            guardar_resposta(mensagem_handoff("erro_interno"))
            resposta = self._fallback_erro_interno(
                conversation_id, config, inicio=inicio, caminho=caminho
            )
            registro.abrir_handoff("erro_interno", "erro_interno")
            # O aviso vai ao cliente e ao histórico como qualquer handoff.
            chave = chave_handoff("handoff:erro_interno", resposta.answer)
            registro.gravar_saida(resposta, {"chave_mensagem": chave}, turno_id=turno_id)
            return resposta

        final, resposta, turno_id = self._fechar(
            conversation_id, config, registro, caminho, metricas, inicio
        )
        if resposta.answer:
            guardar_resposta(resposta.answer)
        if resposta.status == "handoff":
            registro.abrir_handoff("handoff", resposta.handoff_reason, final.get("handoff_detalhe"))
        registro.gravar_saida(resposta, final, turno_id=turno_id)
        return resposta

    def de_sistema(
        self,
        conversation_id: str,
        config: dict[str, Any],
        entrada: dict[str, Any],
        registro: RegistroDoTurno,
        *,
        evento: str,
        forcar: bool,
    ) -> AgentReply:
        """Turno sem mensagem do cliente: só grava saída quando há o que enviar.

        Com ``forcar`` e a conversa com humano, o handoff vira alerta: o aviso
        não vai ao cliente.
        """

        metricas = iniciar_metricas()
        inicio = time.monotonic()
        caminho: list[str] = []
        self._stream(entrada, config, caminho)
        final, resposta, turno_id = self._fechar(
            conversation_id, config, registro, caminho, metricas, inicio
        )
        if forcar and registro.com_humano and resposta.status == "handoff":
            # A conversa já está com humano: o aviso de handoff não vai ao cliente.
            registro.alertar_evento_com_humano(
                {"evento": evento, "motivo": resposta.handoff_reason}
            )
            return resposta
        if resposta.status == "handoff":
            registro.abrir_handoff("handoff", resposta.handoff_reason, final.get("handoff_detalhe"))
        if resposta.answer or resposta.status == "handoff" or final.get("modelo_envio"):
            registro.gravar_saida(resposta, final, turno_id=turno_id)
        return resposta

    def _fechar(
        self,
        conversation_id: str,
        config: dict[str, Any],
        registro: RegistroDoTurno,
        caminho: list[str],
        metricas: TurnMetrics | None,
        inicio: float,
    ) -> tuple[dict[str, Any], AgentReply, int | None]:
        """O que os dois turnos fazem depois do grafo: log, trilha e resposta."""

        final = dict(self.graph.get_state(config).values or {})
        self._log_turno(conversation_id, final, caminho, inicio, metricas)
        turno_id = registro.registrar_turno(final, caminho, metricas, inicio)
        return final, self._evento(conversation_id, final), turno_id

    def _stream(
        self,
        entrada: dict[str, Any],
        config: dict[str, Any],
        caminho: list[str],
    ) -> None:
        """Consome o grafo, guardando o caminho mesmo quando ele falha depois."""

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
            "handoff_em": self._agora().isoformat(),
            "messages": [AIMessage(content=resposta)],
        }
        try:
            self.graph.update_state(config, atualizacao)
        except Exception:
            logger.exception(
                "falha_ao_gravar_erro_interno conversation_id=%s",
                conversation_id,
            )
        self._log_turno(conversation_id, atualizacao, caminho, inicio, metricas_atuais())
        return self._evento(conversation_id, atualizacao, status="handoff")

    @staticmethod
    def _log_turno(
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
