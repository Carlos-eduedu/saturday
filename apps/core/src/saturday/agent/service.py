"""Serviço que executa um turno de conversa."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent import comandos
from saturday.agent.context import AgentContext
from saturday.agent.state import turno_inicial
from saturday.agent.textos import (
    COMANDO_REINICIAR,
    MENSAGEM_REINICIADA,
)
from saturday.agent.turno import RegistroPostgres, Turnos
from saturday.agent.turno import etapa_do_estado as etapa_do_estado
from saturday.canais.base import OrigemCanal
from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import Conversa
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import travar_conversa
from saturday.painel import acoes
from saturday.privacidade import mascarar_conversation_id
from saturday.schemas import MIME_TYPES, AgentReply, Attachment, ChatRequest
from saturday.services.anexos import AnexoInvalido
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


# Campo da ficha editada no painel → chave em `cliente` no ramo INSS.
CAMPOS_FICHA_INSS = {"nome": "nome", "cpf": "cpf", "nascimento": "data_nascimento"}


def ficha_do_estado(estado: dict[str, Any]) -> dict[str, Any]:
    """Dados do cliente com os nomes que `editar_ficha` aceita, nos dois ramos.

    É a leitura par de `AgentService.editar_ficha`: só aqui e lá se sabe onde
    cada ramo guarda cada campo. Devolve só os preenchidos.
    """

    cliente = estado.get("cliente") or {}
    clt = (estado.get("clt") or {}).get("dados") or {}
    ficha = {
        campo: cliente.get(chave) or clt.get(campo) for campo, chave in CAMPOS_FICHA_INSS.items()
    }
    ficha["email"] = clt.get("email")
    ficha["uf"] = cliente.get("uf")
    return {campo: valor for campo, valor in ficha.items() if valor}


@dataclass(frozen=True)
class Jornada:
    """O que o painel lê do estado do grafo, com nome.

    Só `jornada_do_estado` sabe em que chave do estado cada campo vive: fora
    de `agent/`, leia daqui, e não do dicionário do checkpoint.
    """

    ficha: dict[str, Any]
    publico: str | None
    motivo_do_handoff: str | None
    portabilidade: Any
    # Etapa crua do ramo CLT; vazia no INSS (`etapa_do_estado` é a da conversa).
    etapa_clt: str | None
    oferta: dict[str, Any] | None
    # Id da proposta na Granatech para a qual a conversa aponta.
    proposta: str | None
    # Contrato novo no C6 (decisão 0026): a situação e a condição ofertada.
    contrato_novo: dict[str, Any] | None


def jornada_do_estado(estado: dict[str, Any]) -> Jornada:
    clt = estado.get("clt") or {}
    return Jornada(
        ficha=ficha_do_estado(estado),
        publico=estado.get("publico"),
        motivo_do_handoff=estado.get("handoff_reason"),
        portabilidade=estado.get("portability_result"),
        etapa_clt=clt.get("etapa"),
        oferta=clt.get("oferta"),
        proposta=clt.get("proposta"),
        contrato_novo=estado.get("c6_novo"),
    )


class AgentService:
    """Orquestra o grafo, o checkpointer, o outbox e a trava por conversa."""

    def __init__(
        self,
        graph: Any,
        context: AgentContext,
        webhook: WebhookClient,
        settings: Settings,
        fabrica: sessionmaker[Session],
        checkpointer: Any = None,
        storage: Storage | None = None,
    ) -> None:
        self.graph = graph
        self.context = context
        self.webhook = webhook
        self.settings = settings
        self.checkpointer = checkpointer
        # Obrigatória em todo ambiente, testes inclusive (docs/decisoes/0022).
        self.fabrica = fabrica
        self.storage = storage

    @property
    def turnos(self) -> Turnos:
        """Montado a cada uso: os testes trocam `graph` e o relógio deste módulo."""

        return Turnos(self.graph, self.context, self.evento, lambda: agora())

    def config(self, conversation_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": conversation_id}}

    def estado_atual(self, config: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.graph.get_state(config)
        return dict(snapshot.values or {})

    def jornada(self, conversation_id: str) -> Jornada:
        return jornada_do_estado(self.estado_atual(self.config(conversation_id)))

    @contextmanager
    def _trava(self, conversation_id: str) -> Iterator[Session]:
        """Trava a conversa e mantém a transação aberta durante todo o turno.

        A trava é ``pg_advisory_xact_lock``: vale entre processos e some no
        commit. Devolve a sessão porque é dentro desta transação que a resposta
        vai para `mensagens` e para o `outbox`.
        """

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
            "c6_novo": None,
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
        config = self.config(conversation_id)
        with self._trava(conversation_id) as sessao:
            conversa = repositorios.buscar_conversa(sessao, conversation_id)
            if conversa is not None and conversa.atendimento != "ia":
                self._devolver_sem_usuario(sessao, conversa, config)
            else:
                # Já com a IA, ou conversa anterior à Fase 3, só com checkpoint.
                self._liberar_handoff(config)
        return {"conversation_id": conversation_id, "status": "in_progress"}

    def devolver(self, conversa_id: uuid.UUID, usuario_id: uuid.UUID, gestor: bool) -> str:
        """Devolve a conversa à IA a pedido de alguém do painel.

        Tudo sob a trava: a regra de dono, o banco, os alertas e a auditoria
        (`acoes.devolver`) e, antes do commit, o handoff do checkpoint. Se o
        checkpoint falhar, o banco desfaz: banco em `ia` com checkpoint em
        `handoff` reabriria o handoff na próxima mensagem do cliente. Levanta
        `acoes.AcaoRecusada`. Devolve o `conversation_id`.
        """

        with acoes.conversa_travada(self.fabrica, conversa_id) as (sessao, conversa):
            acoes.devolver(sessao, conversa, usuario_id, gestor)
            config = self.config(conversa.conversation_id)
            if self.estado_atual(config):
                self._liberar_handoff(config)
            return conversa.conversation_id

    def _devolver_sem_usuario(
        self, sessao: Session, conversa: Conversa, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Prazo do handoff ou rota `/release`: ninguém do painel agiu.

        Os alertas se resolvem sem usuário e não há auditoria.
        """

        atendimento.devolver(sessao, conversa, None)
        return self._liberar_handoff(config)

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

    def _processar_turno(
        self,
        payload: ChatRequest,
        sessao: Session,
        origem: OrigemCanal | None = None,
        historico: list[dict[str, str]] | None = None,
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

        self._registrar_entrada(sessao, conversa, payload, historico)

        comando = self._comando_de_membro(sessao, conversa, payload)
        if comando is not None:
            return self._executar_comando(comando, payload, config, estado, sessao, conversa)

        silencio, estado = self._silencio_pelo_banco(sessao, conversa, config, estado)
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

    @staticmethod
    def _comando_de_membro(
        sessao: Session, conversa: Conversa, payload: ChatRequest
    ) -> tuple[str, str] | None:
        """Comando de membro testador (decisões 0020 e 0024); de cliente é texto comum."""

        comando = comandos.ler(payload.message or "")
        if comando is None or repositorios.testador(sessao, conversa.telefone) is None:
            return None
        return comando

    def _executar_comando(
        self,
        comando: tuple[str, str],
        payload: ChatRequest,
        config: dict[str, Any],
        estado: dict[str, Any],
        sessao: Session,
        conversa: Conversa,
    ) -> AgentReply:
        """Roda o comando sem passar pelo grafo, fora o `/ir` que abre consulta.

        Vem antes do silêncio com humano: o membro comanda a conversa de teste
        mesmo em handoff ou assumida.
        """

        nome, alvo = comando
        com_humano = conversa.atendimento != "ia"
        jornada = dict(estado.get("clt") or {})

        def dizer(texto: str, chave: str = "comando") -> AgentReply:
            return self._responder_comando(payload, config, sessao, conversa, chave, texto)

        if nome == COMANDO_REINICIAR:
            self._reiniciar(payload, config, estado, conversa)
            aviso = f"\n\n{comandos.REINICIADA_COM_HUMANO}" if com_humano else ""
            return dizer(MENSAGEM_REINICIADA + aviso, "reiniciar")
        if nome == "/ajuda":
            return dizer(comandos.ajuda(self.context.granatech_teste is not None))
        if nome == "/estado":
            return dizer(comandos.estado(jornada, etapa_do_estado(estado), conversa.atendimento))
        if nome == "/humano":
            if com_humano:
                return dizer(comandos.JA_COM_HUMANO)
            self._registro(sessao, conversa).abrir_handoff(
                "handoff", "pediu_humano", {"teste": True}
            )
            return dizer(comandos.ENVIADA_A_HUMANO)
        if nome == "/devolver":
            if not com_humano:
                return dizer(comandos.JA_COM_IA)
            atendimento.devolver(sessao, conversa, None)
            if estado:
                self._liberar_handoff(config)
            return dizer(comandos.DEVOLVIDA)
        if nome not in ("/ir", "/cenario"):
            return dizer(comandos.DESCONHECIDO)
        # Regras 3 e 5: sem a Granatech simulada, nada de pular triagem, SIM ou cota.
        if self.context.granatech_teste is None:
            return dizer(comandos.SEM_SIMULADOR)
        if nome == "/cenario":
            if alvo not in comandos.CENARIOS:
                return dizer(comandos.LISTA_DE_CENARIOS)
            self.graph.update_state(config, {"clt": {**jornada, "cenario": alvo}})
            return dizer(comandos.CENARIO_ESCOLHIDO.format(cenario=alvo))
        if com_humano:
            return dizer(comandos.COM_HUMANO)
        if alvo not in comandos.DESTINOS:
            return dizer(comandos.LISTA_DE_DESTINOS)
        return self._ir(alvo, payload, config, estado, sessao, conversa)

    def _responder_comando(
        self,
        payload: ChatRequest,
        config: dict[str, Any],
        sessao: Session,
        conversa: Conversa,
        chave: str,
        texto: str,
    ) -> AgentReply:
        """Resposta fixa de comando: histórico, outbox e idempotência."""

        estado = self.estado_atual(config)
        # O `message_id` entra no estado: um webhook repetido não roda o comando de novo.
        self._registrar_resposta(
            config,
            list(estado.get("message_ids_recentes") or []),
            dict(estado.get("respostas_recentes") or {}),
            payload.message_id,
            texto,
        )
        resposta = self.evento(payload.conversation_id, {}, status="answered", answer=texto)
        self._registro(sessao, conversa).gravar_saida(resposta, {"chave_mensagem": chave})
        return resposta

    def _reiniciar(
        self,
        payload: ChatRequest,
        config: dict[str, Any],
        estado: dict[str, Any],
        conversa: Conversa,
    ) -> None:
        """Zera a jornada: estado do grafo, etapa e arquivos do estado.

        A conversa, as mensagens e as provas de consentimento ficam no banco. O
        atendimento não muda: com humano, só o `/devolver` traz a IA de volta.
        """

        self._apagar_anexos(estado.get("attachments") or [])
        thread_id = config["configurable"]["thread_id"]
        if hasattr(self.checkpointer, "delete_thread"):
            self.checkpointer.delete_thread(thread_id)
        conversa.etapa = None
        logger.info(
            "conversa_reiniciada conversa_ref=%s conversation_id=%s",
            conversa.id,
            mascarar_conversation_id(payload.conversation_id),
        )

    def _ir(
        self,
        destino: str,
        payload: ChatRequest,
        config: dict[str, Any],
        estado: dict[str, Any],
        sessao: Session,
        conversa: Conversa,
    ) -> AgentReply:
        """`/ir <etapa>`: a jornada CLT parada na etapa, com dados fictícios.

        Até o consentimento, só o estado muda. Para `consultando` e `oferta`,
        um turno de sistema segue do pedido do SIM: a prova, a cota e a consulta
        saem do grafo, na Granatech simulada.
        """

        jornada = comandos.jornada_em(
            destino, conversa.telefone, (estado.get("clt") or {}).get("cenario")
        )
        self.graph.update_state(
            config, {**self._atualizacao_liberacao(), "publico": "clt", "clt": jornada}
        )
        if destino == jornada["etapa"]:
            conversa.etapa = destino
            return self._responder_comando(
                payload, config, sessao, conversa, "comando", comandos.pergunta(jornada)
            )
        # O comando vai como texto do turno: é a resposta guardada na prova de teste.
        entrada = turno_inicial(user_message=payload.message, attachments=[])
        entrada.update(
            self._dados_da_conversa(conversa),
            message_id=payload.message_id,
            evento_sistema=comandos.EVENTO_IR,
        )
        resposta = self.turnos.de_sistema(
            payload.conversation_id,
            config,
            entrada,
            self._registro(sessao, conversa),
            estado=estado,
            evento=comandos.EVENTO_IR,
            forcar=False,
        )
        self._registrar_resposta(
            config,
            list(estado.get("message_ids_recentes") or []),
            dict(estado.get("respostas_recentes") or {}),
            payload.message_id,
            resposta.answer,
        )
        return resposta

    def _conversa(
        self,
        sessao: Session,
        payload: ChatRequest,
        origem: OrigemCanal | None,
    ) -> Conversa:
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
        sessao: Session,
        conversa: Conversa,
        payload: ChatRequest,
        historico: list[dict[str, str]] | None = None,
    ) -> None:
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
            + list(historico or [])
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
            self._registro(sessao, conversa).abrir_handoff("handoff", estado.get("handoff_reason"))
        if conversa.atendimento == "assumida":
            return True, estado
        if conversa.atendimento == "handoff":
            if not self._expirou(conversa.atendimento_em):
                return True, estado
            return False, self._devolver_sem_usuario(sessao, conversa, config)
        return False, estado

    def _registro(self, sessao: Session, conversa: Conversa) -> RegistroPostgres:
        return RegistroPostgres(sessao, conversa, self.webhook, self.fabrica)

    def _liberar_handoff(self, config: dict[str, Any]) -> dict[str, Any]:
        self.graph.update_state(config, self._atualizacao_liberacao())
        return self.estado_atual(config)

    def _rodar_e_fechar(
        self,
        payload: ChatRequest,
        config: dict[str, Any],
        estado: dict[str, Any],
        sessao: Session,
        conversa: Conversa,
        ids_recentes: list[str],
        respostas: dict[str, str],
    ) -> AgentReply:
        entrada = self._entrada_do_grafo(estado, payload)
        entrada.update(self._dados_da_conversa(conversa), message_id=payload.message_id)
        return self.turnos.de_cliente(
            payload.conversation_id,
            config,
            entrada,
            self._registro(sessao, conversa),
            estado=estado,
            guardar_resposta=lambda answer: self._registrar_resposta(
                config, ids_recentes, respostas, payload.message_id, answer
            ),
        )

    @staticmethod
    def _dados_da_conversa(conversa: Conversa) -> dict[str, Any]:
        """O que o ramo CLT precisa da conversa: id (provas, cota) e telefone."""

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
            conversa = repositorios.buscar_conversa(sessao, conversation_id)
            if conversa is None:
                logger.warning(
                    "turno_de_sistema_sem_conversa conversation_id=%s evento=%s",
                    mascarar_conversation_id(conversation_id),
                    evento,
                )
                return None
            if conversa.atendimento != "ia" and not forcar:
                repositorios.abrir_alerta(
                    sessao,
                    "evento_com_humano",
                    conversa_id=conversa.id,
                    detalhe={"evento": evento},
                )
                return None

            entrada = turno_inicial(user_message="", attachments=[])
            entrada.update(self._dados_da_conversa(conversa), evento_sistema=evento)
            return self.turnos.de_sistema(
                conversation_id,
                config,
                entrada,
                self._registro(sessao, conversa),
                estado=estado,
                evento=evento,
                forcar=forcar,
            )

    def desistir_de_sistema(self, conversation_id: str, evento: str) -> None:
        """A fila desistiu do evento: a conversa vai para um humano (`Turnos.desistir`)."""

        with self._trava(conversation_id) as sessao:
            conversa = repositorios.buscar_conversa(sessao, conversation_id)
            if conversa is None:
                logger.warning(
                    "desistencia_sem_conversa conversation_id=%s evento=%s",
                    mascarar_conversation_id(conversation_id),
                    evento,
                )
                return
            self.turnos.desistir(self._registro(sessao, conversa), evento)

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
        *,
        historico: list[dict[str, str]] | None = None,
    ) -> AgentReply:
        """Roda um turno inteiro sob a trava da conversa.

        ``historico``: anexos que vão só para a mensagem no painel, não para o
        grafo (o áudio já transcrito). Só o worker passa; o `/chat` não.
        """

        payload = self._arquivar_anexos(payload)
        with self._trava(payload.conversation_id) as sessao:
            return self._processar_turno(payload, sessao, origem, historico)

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
        """Roda o turno em segundo plano; a entrega é do worker, pelo `outbox`."""

        try:
            self.process_message(payload)
        except Exception as exc:
            logger.error(
                "processamento_falhou conversation_id=%s erro=%s",
                mascarar_conversation_id(payload.conversation_id),
                type(exc).__name__,
            )
