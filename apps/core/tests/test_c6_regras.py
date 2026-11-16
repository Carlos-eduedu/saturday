"""Regras do contrato novo INSS no C6: prazo, teto, parcela e escolha da condição."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from saturday.bancos.c6 import regras
from saturday.bancos.c6.cliente import Simulacao

PEDIDO: dict[str, Any] = {"prazo": 96, "parcela": Decimal("150")}


def condicao(taxa: str, valor: str, observacao: str = "", **extras: Any) -> Simulacao:
    return Simulacao(
        convenio="210177",
        produto="000030",
        valor_cliente=Decimal(valor),
        taxa_mensal=Decimal(taxa),
        observacao=observacao,
        **{"parcelas": 96, "parcela": Decimal("150"), "com_despesa": False, "bruto": {}, **extras},
    )


@pytest.mark.parametrize(
    ("idade", "esperado"),
    [
        (20, None),
        (21, (108, None)),
        (71, (108, None)),
        (72, (96, None)),
        (73, (84, None)),
        (74, (72, Decimal("35000"))),
        (79, (12, Decimal("5000"))),
        (80, None),
    ],
)
def test_prazo_e_teto_pela_idade(idade: int, esperado: object) -> None:
    assert regras.prazo_e_teto(idade) == esperado


def test_parcela_e_99_por_cento_da_margem_truncada() -> None:
    assert regras.parcela_do_contrato_novo(Decimal("161.31")) == Decimal("159.69")
    assert regras.parcela_do_contrato_novo(Decimal("19.99")) is None


def test_escolhe_a_maior_taxa_e_nela_o_maior_valor() -> None:
    escolhida = regras.escolher(
        [
            condicao("1.75", "7000"),
            condicao("1.85", "6000"),
            condicao("1.85", "6200"),
            condicao("1.90", "9000"),  # acima de 1,85%
            condicao("1.85", "6500", observacao="Convênio indisponível"),
            condicao("1.85", "6800", com_despesa=True),  # com seguro
            condicao("1.85", "6900", parcelas=108),  # prazo acima do pedido
            condicao("1.85", "6950", parcela=Decimal("150.01")),  # parcela acima da margem
        ],
        **PEDIDO,
        teto=None,
    )

    assert escolhida is not None
    assert (escolhida.taxa_mensal, escolhida.valor_cliente) == (Decimal("1.85"), Decimal("6200"))


def test_descarta_abaixo_do_minimo_e_acima_do_teto() -> None:
    assert regras.escolher([condicao("1.85", "999.99")], **PEDIDO, teto=None) is None
    assert regras.escolher([condicao("1.85", "5000.01")], **PEDIDO, teto=Decimal("5000")) is None
    assert regras.escolher([condicao("1.85", "5000")], **PEDIDO, teto=Decimal("5000")) is not None
