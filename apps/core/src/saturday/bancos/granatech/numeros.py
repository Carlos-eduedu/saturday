"""Leitura dos números que a Granatech manda.

A API mistura número do JSON, texto em formato brasileiro ("1.500,00") e texto
com ponto decimal ("1500.00"). Dinheiro é sempre ``Decimal``: ``float`` erra
centavos.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_MILHAR = re.compile(r"-?\d{1,3}(\.\d{3})+")


def decimal_de(valor: object) -> Decimal:
    """Converte para ``Decimal``; levanta ``ValueError`` se não for número."""

    if isinstance(valor, bool):
        raise ValueError("booleano não é número")
    if isinstance(valor, int | float):
        return Decimal(str(valor))
    if isinstance(valor, Decimal):
        return valor
    if not isinstance(valor, str):
        raise ValueError(f"tipo sem número: {type(valor).__name__}")

    texto = valor.replace("R$", "").replace(" ", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif _MILHAR.fullmatch(texto):
        # "1.500" é milhar, não um e meio: a API não manda decimal com 3 casas.
        texto = texto.replace(".", "")
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError(f"número inválido: {valor!r}") from exc


def decimal_ou_none(valor: object) -> Decimal | None:
    if valor is None or valor == "":
        return None
    return decimal_de(valor)
