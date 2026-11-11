"""Ajuste ao teto de liberado da MEX (regra 6 do AGENTS.md)."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

PARCELA_MINIMA = Decimal("45")
MAX_NOVAS_SIMULACOES = 4


def proxima_parcela(
    parcela: Decimal, liberado: Decimal, teto: Decimal, tentativa: int
) -> Decimal | None:
    """Parcela para a ``tentativa``-ésima nova simulação (a partir de 1).

    ``floor(parcela × teto / liberado × folga × 100) / 100``, com folga 1 na
    primeira e ``1 − 0,005 × (tentativa − 1)`` nas seguintes. Abaixo de R$ 45
    não há oferta: devolve ``None``.
    """

    folga = Decimal(1) - Decimal("0.005") * (tentativa - 1)
    nova = (parcela * teto / liberado * folga).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    return None if nova < PARCELA_MINIMA else nova
