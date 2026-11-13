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
from saturday.canais.base import CANAIS_WHATSAPP, OrigemCanal
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import travar_conversa
from saturday.metrics import TurnMetrics, iniciar_metricas, metricas_atuais
from saturday.schemas import MIME_TYPES, AgentReply, Attachment, ChatRequest
from saturday.services.anexos import AnexoInvalido
from saturday.services.webhook import WebhookClient
from saturday.settings import TZ_OPERACAO, Settings
from saturday.storage.base import Storage

# Quantos pares mensagem/resposta ficam no checkpoint para idempotência.
JANELA_IDEMPOTENCIA = 50


def etapa_do_estado(estado: dict[str, Any]) -> str | None:
    """Etapa CLT em curso; `inss` na jornada de portabilidade; senão nada."""

    clt = estado.get("clt")
    if isinstance(clt, dict) and clt.get("etapa"):
        return str(clt["etapa"])[:32]
    if estado.get("publico") == "inss" or estado.get("hiscon"):
        return "inss"
    return None


logger = logging.getLogger(__name__)

StatusReply = Literal["answered", "handoff", "with_human", "duplicate"]


def agora() -> datetime:
    """Relógio do serviço; os testes podem substituir esta função."""

    return datetime.now(ZoneInfo(TZ_OPERACAO))


# Campo da ficha editada no painel → chave em `cliente` no ramo INSS.
CAMPOS_FICHA_INSS = {"nome": "nome", "cpf": "cpf", "nascimento": "data_nascimento"}


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
            "tentativas_resposta": 0,
            "handoff_em": None,
        }

    def liberar(self, conversation_id: str) -> dict[str, Any] | None:
        """Devolve a conversa ao agente preservando histórico e dados."""

        if not self.estado_atual(self.config(conversation_id)):
            return None
        with self._trava(conversation_id) as sessao:
            if sessao is not None:
                conversa = repositorios.buscar_conversa(sessao, conversation_id)
                if conversa is not None and conversa.atendimento != "ia":
                    repositorios.mudar_atendimento(sessao, conversa, "ia")
            self.limpar_handoff(conversation_id)
        return {"conversation_id": conversation_id, "status": "in_progress"}

    def limpar_handoff(self, conversation_id: str) -> None:
        """Zera o handoff no checkpoint. Quem responde é decidido em `conversas`."""

        config = self.config(conversation_id)
        if self.estado_atual(config):
            self.graph.update_state(config, self._atualizacao_liberacao())

    def editar_ficha(self, conversation_id: str, campos: dict[str, Any]) -> None:
        """Grava na ficha os dados corrigidos pela equipe no painel.

        Quem chama já segura a trava da conversa (nenhum turno roda junto). O
        ramo CLT guarda em ``clt.dados``; o INSS, em ``cliente``, que só tem
        nome, CPF e nascimento. Sem jornada começada não há ficha a corrigir.
        """

        config = self.config(conversation_id)
        estado = self.estado_atual(config)
        if estado.get("clt"):
            clt = dict(estado["clt"])
            clt["dados"] = {**(clt.get("dados") or {}), **campos}
            self.graph.update_state(config, {"clt": clt})
            return
        if estado.get("cliente"):
            sobra = set(campos) - CAMPOS_FICHA_INSS.keys()
            if sobra:
                raise ValueError(f"o ramo INSS não guarda: {', '.join(sorted(sobra))}")
            cliente = dict(estado["cliente"])
            cliente.update({CAMPOS_FICHA_INSS[c]: v for c, v in campos.items()})
            self.graph.update_state(config, {"cliente": cliente})
            return
        raise ValueError("a conversa ainda não tem ficha")

    def _expirou(self, desde: datetime | None) -> bool:
        if self.settings.handoff_auto_release_horas <= 0 or desde is None:
            return False
        return agora() - desde > timedelta(hours=self.settings.handoff_auto_release_horas)

    def _deve_liberar_auto(self, estado: dict[str, Any]) -> bool:
        if estado.get("status") != "handoff":
            return False
        return self._expirou(self._parse_iso(estado.get("handoff_em")))

    @staticmethod
    def _registrar_turno(
        sessao: Session,
        conversa: Conversa,
        estado: dict[str, Any],
        caminho: list[str],
        metricas: TurnMetrics | None,
    ) -> None:
        """Etapa na conversa (para a lista) e a trilha do turno (aba "IA").

        Só códigos, números e tempos: nenhum texto do cliente ou do modelo.
        """

        conversa.etapa = etapa_do_estado(estado)
        resumo = metricas.resumo() if metricas else {"chamadas": [], "custo_total_usd": 0.0}
        classificou = "classify_intent" in caminho
        sessao.add(
            Turno(
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
            )
        )

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
        origem: OrigemCanal | None = None,
    ) -> AgentReply:
        """Um turno, em etapas: estado, conversa, dedupe, entrada, grafo, saída."""

        config = self.config(payload.conversation_id)
        estado = self._aplicar_retencao(config, self.estado_atual(config))
        conversa = self._conversa(sessao, payload, origem)

        ids_recentes = list(estado.get("message_ids_recentes") or [])
        respostas = dict(estado.get("respostas_recentes") or {})

        duplicada = self._resposta_duplicada(payload, estado, respostas)
        if duplicada is not None:
            return duplicada

        self._registrar_entrada(sessao, conversa, payload)

        if sessao is not None and conversa is not None:
            silencio, estado = self._silencio_pelo_banco(sessao, conversa, config, estado)
        else:
            silencio, estado = self._silencio_pelo_checkpoint(config, estado)
        if silencio:
            return self._resposta_em_handoff(payload, estado)

        return self._rodar_e_fechar(
            payload,
            config,
            estado,
            sessao,
            conversa,
            ids_recentes,
            respostas,
        )

    def _conversa(
        self,
        sessao: Session | None,
        payload: ChatRequest,
        origem: OrigemCanal | None,
    ) -> Conversa | None:
        if sessao is None:
            return None
        return repositorios.obter_ou_criar_conversa(
            sessao,
            payload.conversation_id,
            canal=origem.canal if origem else "chat",
            telefone=origem.telefone if origem else None,
            phone_number_id=origem.phone_number_id if origem else None,
        )

    def _resposta_duplicada(
        self,
        payload: ChatRequest,
        estado: dict[str, Any],
        respostas: dict[str, str],
    ) -> AgentReply | None:
        """O mesmo `message_id` devolve a resposta já dada, não uma vazia."""

        if not payload.message_id:
            return None
        if payload.message_id not in list(estado.get("message_ids_recentes") or []):
            return None
        return self.evento(
            payload.conversation_id,
            estado,
            status="duplicate",
            answer=respostas.get(payload.message_id, ""),
        )

    def _registrar_entrada(
        self,
        sessao: Session | None,
        conversa: Conversa | None,
        payload: ChatRequest,
    ) -> None:
        if sessao is None or conversa is None:
            return
        repositorios.registrar_entrada(
            sessao,
            conversa,
            message_id=payload.message_id,
            conteudo=payload.message,
            anexos=[
                {"chave": anexo.chave, "mime_type": anexo.mime_type}
                for anexo in payload.attachments
                if anexo.chave
            ]
            or None,
        )

    def _resposta_em_handoff(
        self,
        payload: ChatRequest,
        estado: dict[str, Any],
    ) -> AgentReply:
        return self.evento(
            payload.conversation_id,
            estado,
            status="with_human",
            answer="",
        )

    def _silencio_pelo_banco(
        self,
        sessao: Session,
        conversa: Conversa,
        config: dict[str, Any],
        estado: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """A IA fica calada em `handoff` e `assumida` (docs/decisoes/0003).

        A liberação automática vale só para o handoff sem dono: conversa
        assumida só volta para a IA quando alguém a devolve.
        """

        if conversa.atendimento == "ia" and estado.get("status") == "handoff":
            # Handoff anterior à Fase 3, gravado só no checkpoint.
            repositorios.mudar_atendimento(sessao, conversa, "handoff")
        if conversa.atendimento == "assumida":
            return True, estado
        if conversa.atendimento == "handoff":
            if not self._expirou(conversa.atendimento_em):
                return True, estado
            repositorios.mudar_atendimento(sessao, conversa, "ia")
            return False, self._liberar_handoff(config)
        return False, estado

    def _silencio_pelo_checkpoint(
        self,
        config: dict[str, Any],
        estado: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Sem Postgres (`pytest`), o handoff continua só no checkpoint."""

        if estado.get("status") != "handoff":
            return False, estado
        if not self._deve_liberar_auto(estado):
            return True, estado
        return False, self._liberar_handoff(config)

    @staticmethod
    def _abrir_handoff(
        sessao: Session,
        conversa: Conversa,
        tipo_alerta: str,
        motivo: str | None,
        detalhe: dict[str, Any] | None = None,
    ) -> None:
        repositorios.mudar_atendimento(sessao, conversa, "handoff")
        repositorios.abrir_alerta(
            sessao,
            tipo_alerta,
            conversa_id=conversa.id,
            detalhe={"motivo": motivo, **(detalhe or {})},
        )

    def _liberar_handoff(self, config: dict[str, Any]) -> dict[str, Any]:
        self.graph.update_state(config, self._atualizacao_liberacao())
        return self.estado_atual(config)

    def _rodar_e_fechar(
        self,
        payload: ChatRequest,
        config: dict[str, Any],
        estado: dict[str, Any],
        sessao: Session | None,
        conversa: Conversa | None,
        ids_recentes: list[str],
        respostas: dict[str, str],
    ) -> AgentReply:
        entrada = self._entrada_do_grafo(estado, payload)
        entrada.update(self._dados_da_conversa(conversa), message_id=payload.message_id)
        metricas = iniciar_metricas()
        inicio = time.monotonic()
        caminho: list[str] = []
        try:
            self._stream(entrada, config, caminho)
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
            if sessao is not None and conversa is not None:
                self._abrir_handoff(sessao, conversa, "erro_interno", "erro_interno")
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
        if sessao is not None and conversa is not None:
            self._registrar_turno(sessao, conversa, final, caminho, metricas)
        resposta = self.evento(payload.conversation_id, final)

        if payload.message_id and resposta.answer:
            self._registrar_resposta(
                config, ids_recentes, respostas, payload.message_id, resposta.answer
            )
        if sessao is not None and conversa is not None:
            if resposta.status == "handoff":
                self._abrir_handoff(
                    sessao,
                    conversa,
                    "handoff",
                    resposta.handoff_reason,
                    final.get("handoff_detalhe"),
                )
            self._gravar_saida(sessao, conversa, resposta, final)
        return resposta

    @staticmethod
    def _dados_da_conversa(conversa: Conversa | None) -> dict[str, Any]:
        """O que o ramo CLT precisa da conversa: id (provas, cota) e telefone."""

        if conversa is None:
            return {}
        return {"conversa_ref": str(conversa.id), "telefone": conversa.telefone}

    def continuar(
        self, conversation_id: str, evento: str, *, forcar: bool = False
    ) -> AgentReply | None:
        """Turno de sistema: segue a jornada sem mensagem do cliente.

        Usado quando a Granatech avisa que a consulta mudou e pelo recontato. Com
        a conversa em handoff ou assumida, a IA não fala: vira alerta para quem
        está com ela. ``forcar`` é o gestor pedindo pelo painel (reenviar o link
        de biometria): o turno roda mesmo com humano. Devolve ``None`` quando
        nada rodou.
        """

        with self._trava(conversation_id) as sessao:
            config = self.config(conversation_id)
            estado = self.estado_atual(config)
            conversa = repositorios.buscar_conversa(sessao, conversation_id) if sessao else None
            if sessao is not None and conversa is not None:
                if conversa.atendimento != "ia" and not forcar:
                    repositorios.abrir_alerta(
                        sessao,
                        "evento_com_humano",
                        conversa_id=conversa.id,
                        detalhe={"evento": evento},
                    )
                    return None
            elif estado.get("status") == "handoff" and not forcar:
                return None

            entrada = turno_inicial(user_message="", attachments=[])
            entrada.update(self._dados_da_conversa(conversa), evento_sistema=evento)
            caminho: list[str] = []
            inicio = time.monotonic()
            metricas = iniciar_metricas()
            self._stream(entrada, config, caminho)
            final = dict(self.graph.get_state(config).values or {})
            self._log_turno(conversation_id, final, caminho, inicio, metricas)
            if sessao is not None and conversa is not None:
                self._registrar_turno(sessao, conversa, final, caminho, metricas)
            resposta = self.evento(conversation_id, final)
            if sessao is not None and conversa is not None:
                if forcar and conversa.atendimento != "ia" and resposta.status == "handoff":
                    # A conversa já está com humano: o aviso de handoff não vai ao cliente.
                    repositorios.abrir_alerta(
                        sessao,
                        "evento_com_humano",
                        conversa_id=conversa.id,
                        detalhe={"evento": evento, "motivo": resposta.handoff_reason},
                    )
                    return resposta
                if resposta.status == "handoff":
                    self._abrir_handoff(
                        sessao,
                        conversa,
                        "handoff",
                        resposta.handoff_reason,
                        final.get("handoff_detalhe"),
                    )
                if resposta.answer or resposta.status == "handoff" or final.get("modelo_envio"):
                    self._gravar_saida(sessao, conversa, resposta, final)
            return resposta

    def _entrada_do_grafo(
        self,
        estado: dict[str, Any],
        payload: ChatRequest,
    ) -> dict[str, Any]:
        entrada = turno_inicial(
            user_message=payload.message,
            attachments=[
                anexo.model_dump(mode="json", exclude_none=True) for anexo in payload.attachments
            ],
        )
        cliente = self._cliente_mesclado(estado, payload)
        if cliente:
            entrada["cliente"] = cliente
        if payload.message.strip():
            entrada["messages"] = [HumanMessage(content=payload.message)]
        return entrada

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

    def _gravar_saida(
        self,
        sessao: Session,
        conversa: Conversa,
        resposta: AgentReply,
        final: dict[str, Any] | None = None,
    ) -> None:
        """Histórico da resposta e, quando houver canal, o envio no outbox.

        ``final`` (o estado do turno) pode pedir um modelo: ``modelo_envio`` sai
        sempre como modelo (marketing); ``modelo_aviso`` e ``link_aviso`` são o
        aviso usado se a janela de 24 h estiver fechada.
        """

        final = final or {}
        if final.get("marketing") in ("opt_in", "opt_out"):
            conversa.marketing = final["marketing"]
        modelo_envio = final.get("modelo_envio")
        conteudo = resposta.answer or (f"[modelo {modelo_envio}]" if modelo_envio else "")
        mensagem_id = repositorios.registrar_saida(sessao, conversa, conteudo=conteudo)
        canal = self._canal_de_saida(conversa, resposta)
        if canal is None:
            return
        # O id volta no payload: é nesta linha que o worker grava o `wamid` e o
        # status de entrega quando a Meta confirmar.
        payload = self._payload_de_saida(conversa, resposta, canal)
        payload["mensagem_id"] = mensagem_id
        if canal in CANAIS_WHATSAPP:
            for chave, destino in (
                ("modelo_envio", "modelo"),
                ("modelo_aviso", "modelo_aviso"),
                ("link_aviso", "link_aviso"),
            ):
                if final.get(chave):
                    payload[destino] = final[chave]
        enfileirar(sessao, conversa_id=conversa.id, canal=canal, payload=payload)

    def _canal_de_saida(self, conversa: Conversa, resposta: AgentReply) -> str | None:
        """Quem entrega esta resposta.

        No WhatsApp (Meta ou Evolution) a resposta sempre passa pelo outbox, inclusive no handoff —
        o cliente precisa saber que a conversa foi para uma pessoa. No webhook,
        o handoff continua não gerando envio, como antes.
        """

        if resposta.status == "duplicate":
            return None
        if conversa.canal in CANAIS_WHATSAPP:
            return conversa.canal
        if self.webhook.configurado and resposta.status != "with_human":
            return "webhook"
        return None

    @staticmethod
    def _payload_de_saida(
        conversa: Conversa,
        resposta: AgentReply,
        canal: str,
    ) -> dict[str, Any]:
        payload = resposta.model_dump(mode="json")
        if canal in CANAIS_WHATSAPP:
            payload["numero"] = conversa.telefone
            payload["phone_number_id"] = conversa.phone_number_id
        return payload

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

    def process_message(
        self,
        payload: ChatRequest,
        origem: OrigemCanal | None = None,
    ) -> AgentReply:
        """Roda um turno inteiro sob a trava da conversa."""

        payload = self._arquivar_anexos(payload)
        with self._trava(payload.conversation_id) as sessao:
            return self._processar_turno(payload, sessao, origem)

    def _arquivar_anexos(self, payload: ChatRequest) -> ChatRequest:
        """Leva para o storage o que veio por `url` ou `base64`.

        O estado do grafo passa a guardar só a chave: base64 no checkpoint
        incha cada versão do estado e espalha dado pessoal por todas elas.
        """

        if not payload.attachments or self.storage is None:
            return payload

        arquivados: list[Attachment] = []
        for anexo in payload.attachments:
            if anexo.chave is not None:
                arquivados.append(anexo)
                continue
            try:
                carregado = self.context.anexos.carregar_anexo(
                    anexo.model_dump(mode="json", exclude_none=True)
                )
            except AnexoInvalido:
                # Mantém como veio: o nó reporta o anexo inválido como antes.
                arquivados.append(anexo)
                continue
            # `_normalizar_mime` já recusou o que não está em `MIME_ACEITOS`,
            # então o valor aqui é sempre um dos tipos aceitos pelo schema.
            mime = cast(MIME_TYPES, carregado.mime_type)
            chave = self.storage.salvar(carregado.data, mime_type=mime)
            arquivados.append(Attachment(chave=chave, mime_type=mime))
        return payload.model_copy(update={"attachments": arquivados})

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
