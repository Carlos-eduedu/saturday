"""Estado compartilhado entre os nós do grafo."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import MessagesState


class AgentState(MessagesState, total=False):
    # Campos do turno corrente. O serviço que invoca o grafo zera todos eles.
    user_message: str
    attachments: list[dict[str, Any]]
    intent: str | None
    intent_confidence: float | None
    needs_human: bool
    status: Literal["in_progress", "answered", "handoff"]
    answer: str | None
    handoff_reason: str | None
    resposta_oferta: str | None
    # Ramo CLT: evento do sistema que abriu o turno (sem mensagem do cliente),
    # dados da conversa vindos do serviço e o desvio para a FAQ.
    evento_sistema: str | None
    conversa_ref: str | None
    message_id: str | None
    telefone: str | None
    clt_faq: bool
    # Saída do turno além do texto: modelo para a janela fechada (com o código do
    # link curto), modelo enviado sempre (marketing) e detalhe do alerta de handoff.
    modelo_aviso: str | None
    link_aviso: str | None
    modelo_envio: str | None
    handoff_detalhe: dict[str, Any] | None
    # Opt-in/opt-out de marketing a gravar em `conversas` pelo serviço.
    marketing: str | None

    # Campos persistentes da conversa.
    publico: str | None
    cliente: dict[str, Any]
    hiscon: dict[str, Any] | None
    hiscon_recebido_em: str | None
    aguardando: Literal["data_nascimento", "uf"] | None
    tentativas_coleta: int
    tentativas_extrato: int
    # Respostas seguidas sem FAQ fora de jornada: a 2ª vai para a equipe.
    tentativas_resposta: int
    portability_result: dict[str, Any] | None
    oferta_pendente: bool
    # Jornada CLT: etapa, passo, dados informados e oferta (ver agent/clt).
    clt: dict[str, Any]
    handoff_em: str | None
    # Sem reducer de propósito: a lista é substituída a cada gravação.
    message_ids_recentes: list[str]
    # Resposta já dada por `message_id`, para o repetido devolver o mesmo texto.
    respostas_recentes: dict[str, str]


CAMPOS_DO_TURNO = (
    "intent",
    "intent_confidence",
    "needs_human",
    "answer",
    "handoff_reason",
    "resposta_oferta",
    "evento_sistema",
    "conversa_ref",
    "message_id",
    "telefone",
    "clt_faq",
    "modelo_aviso",
    "link_aviso",
    "modelo_envio",
    "handoff_detalhe",
    "marketing",
)


def turno_inicial(
    *,
    user_message: str,
    attachments: list[dict[str, Any]],
    cliente: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Campos que precisam ser reiniciados a cada turno."""

    estado: dict[str, Any] = {
        "user_message": user_message,
        "attachments": attachments,
        "intent": None,
        "intent_confidence": None,
        "needs_human": False,
        "status": "in_progress",
        "answer": None,
        "handoff_reason": None,
        "resposta_oferta": None,
        "evento_sistema": None,
        "conversa_ref": None,
        "message_id": None,
        "telefone": None,
        "clt_faq": False,
        "modelo_aviso": None,
        "link_aviso": None,
        "modelo_envio": None,
        "handoff_detalhe": None,
        "marketing": None,
    }
    if cliente:
        estado["cliente"] = cliente
    return estado
