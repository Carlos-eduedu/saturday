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
