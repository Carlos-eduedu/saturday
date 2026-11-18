"""Regras do contrato novo INSS no C6 (decisão 0026): as mesmas da operação da MEX."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from saturday.bancos.c6.cliente import Simulacao

IDADE_MIN, IDADE_MAX = 21, 79
PRAZO_PADRAO = 108
# Idade → (prazo máximo, teto do valor na conta). Sem teto até os 73 anos.
_FAIXAS: dict[int, tuple[int, Decimal | None]] = {
    72: (96, None),
    73: (84, None),
    74: (72, Decimal("35000")),
    75: (60, Decimal("20000")),
    76: (48, Decimal("15000")),
    77: (36, Decimal("10000")),
    78: (24, Decimal("8000")),
    79: (12, Decimal("5000")),
}
MARGEM_MINIMA = Decimal("20")
FATOR_DA_MARGEM = Decimal("0.99")
VALOR_MINIMO = Decimal("1000")
TAXA_MAXIMA = Decimal("1.85")


def prazo_e_teto(idade: int) -> tuple[int, Decimal | None] | None:
    """Prazo máximo e teto pela idade; ``None`` quando o C6 não faz."""

    if not IDADE_MIN <= idade <= IDADE_MAX:
        return None
    return _FAIXAS.get(idade, (PRAZO_PADRAO, None))


def faixas() -> list[tuple[int, int, int, Decimal | None]]:
    """Idade de, idade até, prazo máximo e teto, em ordem: para o painel mostrar as regras."""

    return [
        (IDADE_MIN, min(_FAIXAS) - 1, PRAZO_PADRAO, None),
        *((idade, idade, *_FAIXAS[idade]) for idade in sorted(_FAIXAS)),
    ]


def parcela_do_contrato_novo(margem_livre: Decimal) -> Decimal | None:
    """99% da margem livre, truncada nos centavos; ``None`` abaixo da margem mínima."""

    if margem_livre < MARGEM_MINIMA:
        return None
    return (margem_livre * FATOR_DA_MARGEM).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def escolher(
    condicoes: list[Simulacao], *, prazo: int, parcela: Decimal, teto: Decimal | None
) -> Simulacao | None:
    """Faixa de maior taxa até 1,85% a.m. e, nela, o maior valor na conta.

    Só vale condição dentro do pedido (prazo da idade, parcela na margem) e sem
    despesa cobrada: a oferta do Saturday não leva seguro.
    """

    validas = [
        c
        for c in condicoes
        if not c.observacao
        and not c.com_despesa
        and c.parcelas <= prazo
        and c.parcela <= parcela
        and 0 < c.taxa_mensal <= TAXA_MAXIMA
        and c.valor_cliente >= VALOR_MINIMO
        and (teto is None or c.valor_cliente <= teto)
    ]
    return max(validas, key=lambda c: (c.taxa_mensal, c.valor_cliente), default=None)
