"""Ordem dos status de consulta e proposta, para eventos fora de ordem.

Um evento só muda o registro se avança na jornada. Status final nunca é
sobrescrito. As exceções são as regressões que a própria Granatech provoca
(refazer a biometria, falha no pagamento): voltam etapas de propósito.
"""

from __future__ import annotations

FINAL = 100

CONSULTA: dict[str, int] = {
    "AWAITING_CLIENT_AUTHORIZATION": 0,
    "PENDING": 1,
    "PROCESSING": 2,
    "SUCCESS": FINAL,
    "NO_MARGIN": FINAL,
    "USED": FINAL,
    "UNEXPECTED_ERROR": FINAL,
    # TODO(granatech): significado destes dois; por ora viram alerta.
    "FIDUCIARY_INSTITUTION_NO_AUTHORIZATION": FINAL,
    "WORKER_MUST_CANCEL_RETURN_REQUEST": FINAL,
}

# A documentação lista os status em inglês, mas a api-dev manda o webhook de
# consulta em português (worker do dev, 2026-11-13: rodadas 6 a 8 da
# homologação). Só os nomes já vistos; o resto continua virando alerta.
# TODO(granatech): lista completa dos status de consulta em português.
SINONIMOS_CONSULTA = {
    "AGUARDANDO_AUTORIZACAO_DO_CLIENTE": "AWAITING_CLIENT_AUTHORIZATION",
    "CONCLUIDO": "SUCCESS",
}


def normalizar_consulta(status: str) -> str:
    """Status de consulta no nome da documentação (inglês), venha como vier."""

    return SINONIMOS_CONSULTA.get(status, status)


# Consultas que não servem para reaproveitar: a próxima precisa ser nova.
CONSULTA_SEM_REAPROVEITAMENTO = frozenset(
    {
        "UNEXPECTED_ERROR",
        "FIDUCIARY_INSTITUTION_NO_AUTHORIZATION",
        "WORKER_MUST_CANCEL_RETURN_REQUEST",
    }
)
# Status que pedem atenção humana logo que chegam.
CONSULTA_ALERTA = CONSULTA_SEM_REAPROVEITAMENTO

PROPOSTA: dict[str, int] = {
    "PENDING_CONFIRMATION": 0,
    "PENDING_USER_REVIEW": 1,
    "PENDING_FORMALIZATION": 2,
    "PENDING_REFORMALIZATION": 2,
    "PENDING_BANK_ANALYSIS": 3,
    "PENDING_PAYMENT": 4,
    "PAYED": FINAL,
    "CANCELED": FINAL,
    "REPROVED": FINAL,
    "CANCELED_BY_CLIENT": FINAL,
}

# `PAGO` e `PROPOSTA_PAGA` chegam como notificação e valem pagamento.
NOTIFICACAO_PAGA = frozenset({"PAGO", "PROPOSTA_PAGA"})
REGRESSOES_LEGITIMAS = frozenset({"REFAZER_SEGURANCA_IDENTIDADE", "FALHA_PAGAMENTO"})


# A api-dev manda o webhook de proposta com o nome da notificação em `status` e
# sem `tipo_notificacao` (rodada 11 da homologação, 2026-11-13). Cada
# notificação tem um status só, na tabela de docs/granatech-homologacao/
# webhook-propostas.md.
STATUS_DA_NOTIFICACAO = {
    "AGUARDANDO_CONFIRMACAO": "PENDING_CONFIRMATION",
    "AGUARDANDO_REVISAO_USUARIO": "PENDING_USER_REVIEW",
    "FALHA_PAGAMENTO": "PENDING_USER_REVIEW",
    "AGUARDANDO_FORMALIZACAO": "PENDING_FORMALIZATION",
    "FORMALIZACAO_EM_ANDAMENTO": "PENDING_FORMALIZATION",
    "BLOQUEIO_DE_SALDO_EM_ANDAMENTO": "PENDING_FORMALIZATION",
    "BLOQUEIO_SALDO": "PENDING_FORMALIZATION",
    "REFAZER_SEGURANCA_IDENTIDADE": "PENDING_REFORMALIZATION",
    "AGUARDANDO_ANALISE_BANCO": "PENDING_BANK_ANALYSIS",
    "SUCESSO_SEGURANCA_IDENTIDADE": "PENDING_PAYMENT",
    "REPROVADO": "REPROVED",
    "PROPOSTA_CANCELADA": "CANCELED",
    "BLOQUEIO_DE_SALDO_CANCELADO": "CANCELED",
    "PAGO": "PAYED",
    "PROPOSTA_PAGA": "PAYED",
}


def ler_evento_proposta(payload: dict[str, object]) -> tuple[str, str | None]:
    """Status efetivo e notificação de um webhook de proposta, nos dois formatos.

    Documentado: ``status_da_proposta`` + ``tipo_notificacao``. Da api-dev: só
    ``status``, com o nome da notificação.
    """

    bruto = str(payload.get("status_da_proposta") or payload.get("status") or "")
    valor = payload.get("tipo_notificacao")
    notificacao = str(valor) if valor else None
    if bruto in STATUS_DA_NOTIFICACAO:
        notificacao = notificacao or bruto
        bruto = STATUS_DA_NOTIFICACAO[bruto]
    return status_da_proposta(bruto, notificacao) or "", notificacao


def status_da_proposta(status: str | None, notificacao: str | None) -> str | None:
    """Status efetivo do evento de proposta (``PAGO`` vira ``PAYED``)."""

    if notificacao in NOTIFICACAO_PAGA:
        return "PAYED"
    return status


def aceita_consulta(atual: str | None, novo: str) -> bool:
    return _aceita(CONSULTA, atual, novo, regressao=False)


def aceita_proposta(atual: str | None, novo: str, notificacao: str | None) -> bool:
    return _aceita(PROPOSTA, atual, novo, regressao=notificacao in REGRESSOES_LEGITIMAS)


def _aceita(ordem: dict[str, int], atual: str | None, novo: str, *, regressao: bool) -> bool:
    if novo not in ordem:
        return False
    if atual is None or atual not in ordem:
        return True
    if ordem[atual] == FINAL:
        return False
    return regressao or ordem[novo] >= ordem[atual]


def final(ordem: dict[str, int], status: str | None) -> bool:
    return status is not None and ordem.get(status) == FINAL


# O que a conversa faz com cada evento de proposta (AGENTS.md, tabela de status).
# A notificação é mais específica que o status: ela manda; o status é a reserva.
ACAO_POR_NOTIFICACAO = {
    "AGUARDANDO_CONFIRMACAO": "criada",
    "AGUARDANDO_FORMALIZACAO": "formalizar",
    "REFAZER_SEGURANCA_IDENTIDADE": "refazer",
    "BLOQUEIO_DE_SALDO_EM_ANDAMENTO": "silencio",
    "BLOQUEIO_SALDO": "silencio",
    "FORMALIZACAO_EM_ANDAMENTO": "silencio",
    "AGUARDANDO_ANALISE_BANCO": "analise",
    "SUCESSO_SEGURANCA_IDENTIDADE": "identidade_ok",
    "AGUARDANDO_REVISAO_USUARIO": "revisao",
    "FALHA_PAGAMENTO": "falha_pagamento",
    "REPROVADO": "reprovada",
    "PAGO": "paga",
    "PROPOSTA_PAGA": "paga",
}
ACAO_POR_STATUS = {
    "PENDING_CONFIRMATION": "criada",
    "PENDING_FORMALIZATION": "formalizar",
    "PENDING_REFORMALIZATION": "refazer",
    "PENDING_BANK_ANALYSIS": "analise",
    "PENDING_PAYMENT": "identidade_ok",
    "PENDING_USER_REVIEW": "revisao",
    "REPROVED": "reprovada",
    "CANCELED": "cancelada",
    "CANCELED_BY_CLIENT": "cancelada",
    "PAYED": "paga",
}


def acao_da_proposta(status: str | None, notificacao: str | None) -> str:
    """Ação da conversa para um evento de proposta; ``desconhecida`` faz handoff."""

    if status in ("CANCELED", "CANCELED_BY_CLIENT"):
        return "cancelada"
    if notificacao in ACAO_POR_NOTIFICACAO:
        return ACAO_POR_NOTIFICACAO[notificacao]
    return ACAO_POR_STATUS.get(status or "", "desconhecida")
