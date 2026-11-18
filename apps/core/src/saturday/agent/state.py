"""Estado compartilhado entre os nós do grafo."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage
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
    # Chave da mensagem fixa da resposta (`+` quando junta várias); nula quando
    # o modelo escreveu (decisão 0018).
    chave_mensagem: str | None
    handoff_reason: str | None
    resposta_oferta: str | None
    # Ramo CLT: evento do sistema que abriu o turno (sem mensagem do cliente),
    # dados da conversa vindos do serviço e o desvio para a FAQ.
    evento_sistema: str | None
    conversa_ref: str | None
    message_id: str | None
    telefone: str | None
    clt_faq: bool
    # Para onde o nó do iCred manda o turno: de volta ao classificador ou ao
    # cálculo da portabilidade (o caminho de antes do iCred).
    icred_rota: str | None
    # A dúvida veio logo depois de um pedido do iCred: respondida, o pedido
    # sai de novo no mesmo turno, por último.
    icred_repetir: bool
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
    aguardando: Literal["data_nascimento", "uf", "cpf", "consentimento_c6", "renda"] | None
    tentativas_coleta: int
    tentativas_extrato: int
    # Respostas seguidas sem FAQ fora de jornada: a 2ª vai para a equipe.
    tentativas_resposta: int
    portability_result: dict[str, Any] | None
    oferta_pendente: bool
    # Contrato novo no C6: `situacao` (ofertado, aceito, recusado, sem_oferta) e a
    # condição ofertada.
    c6_novo: dict[str, Any] | None
    # Jornada CLT: etapa, passo, dados informados e oferta (ver agent/clt).
    clt: dict[str, Any]
    # Consulta e oferta do iCred no ramo INSS: etapa, consulta e pacote (ver agent/icred).
    icred: dict[str, Any]
    handoff_em: str | None
    # Id da última mensagem de atendente já contada por uma devolução à IA: só
    # fala mais nova que essa deixa a marca de atendimento (decisão 0033).
    fala_atendente: int
    # Sem reducer de propósito: a lista é substituída a cada gravação.
    message_ids_recentes: list[str]
    # Resposta já dada por `message_id`, para o repetido devolver o mesmo texto.
    respostas_recentes: dict[str, str]


def marca_de_atendimento_humano() -> AIMessage:
    """O que a devolução à IA põe no histórico: houve conversa com um atendente.

    A fala do atendente não entra no grafo. A marca, vazia, passa a ser a
    última mensagem do agente: o pedido ou a oferta de antes deixa de ser "o
    que o cliente viu por último" até a IA mostrá-lo de novo. O histórico que
    vai ao modelo pula mensagem vazia.
    """

    return AIMessage(content="")


def ultima_mensagem_agente(state: AgentState) -> str | None:
    """O que o cliente viu por último: um SIM só vale como resposta a isso (regra 3).

    Texto vazio quando a conversa voltou de um atendente e a IA ainda não falou.
    """

    for mensagem_atual in reversed(state.get("messages") or []):
        if not isinstance(mensagem_atual, AIMessage):
            continue
        conteudo = mensagem_atual.content
        return conteudo if isinstance(conteudo, str) else str(conteudo)
    return None


def falas_desde_o_atendimento(state: AgentState) -> list[str] | None:
    """O que o agente disse depois da última marca de atendimento humano.

    ``None`` quando não há marca: a conversa nunca voltou de um atendente que
    escreveu ao cliente. Um pedido de antes do atendente só volta a valer
    quando aparece nesta lista, isto é, quando foi mostrado de novo.
    """

    falas: list[str] = []
    for mensagem_atual in reversed(state.get("messages") or []):
        if not isinstance(mensagem_atual, AIMessage):
            continue
        conteudo = mensagem_atual.content
        if conteudo == "":
            return falas
        falas.append(conteudo if isinstance(conteudo, str) else str(conteudo))
    return None


CAMPOS_DO_TURNO = (
    "intent",
    "intent_confidence",
    "needs_human",
    "answer",
    "chave_mensagem",
    "handoff_reason",
    "resposta_oferta",
    "evento_sistema",
    "conversa_ref",
    "message_id",
    "telefone",
    "clt_faq",
    "icred_rota",
    "icred_repetir",
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
        "chave_mensagem": None,
        "handoff_reason": None,
        "resposta_oferta": None,
        "evento_sistema": None,
        "conversa_ref": None,
        "message_id": None,
        "telefone": None,
        "clt_faq": False,
        "icred_rota": None,
        "icred_repetir": False,
        "modelo_aviso": None,
        "link_aviso": None,
        "modelo_envio": None,
        "handoff_detalhe": None,
        "marketing": None,
    }
    if cliente:
        estado["cliente"] = cliente
    return estado
