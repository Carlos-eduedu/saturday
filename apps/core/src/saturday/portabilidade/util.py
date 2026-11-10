"""Utilitários compartilhados do domínio de portabilidade."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def numero_brasileiro(valor: Any) -> float | None:
    """Converte "1.234,56" em 1234.56. Inválido vira None, nunca zero."""

    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if not isinstance(valor, str):
        return None

    texto = valor.strip().replace("R$", "").replace("%", "").replace("\u00a0", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def parse_data(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def parse_mes_ano(valor: Any) -> tuple[int, int] | None:
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    for formato in ("%m/%Y", "%m/%y"):
        try:
            data = datetime.strptime(texto, formato)
            return data.year, data.month
        except ValueError:
            continue
    return None


def contrato_ativo(situacao: Any) -> bool:
    return isinstance(situacao, str) and situacao.strip().lower().startswith("ativo")
