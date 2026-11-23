"""Dado sem máscara sai formatado (decisão 0037); mascarado, como sempre."""

from __future__ import annotations

import pytest

from saturday.privacidade import exibir


@pytest.mark.parametrize(
    ("campo", "valor", "formatado"),
    [
        ("cpf", "00189004967", "001.890.049-67"),
        ("telefone", "5511987654321", "+55 (11) 98765-4321"),
        ("telefone", "551133334444", "+55 (11) 3333-4444"),
        ("telefone", "11987654321", "(11) 98765-4321"),
        ("data_nascimento", "1990-05-15", "15/05/1990"),
        ("email", "maria@exemplo.test", "maria@exemplo.test"),
        # Fora do formato esperado, passa como veio: melhor cru que errado.
        ("cpf", "123", "123"),
        ("telefone", "+1 202 555", "+1 202 555"),
        ("data_nascimento", "15/05/1990", "15/05/1990"),
    ],
)
def test_sem_mascara_sai_formatado(campo: str, valor: str, formatado: str) -> None:
    assert exibir(campo, valor, True) == formatado


def test_com_mascara_nao_muda() -> None:
    assert exibir("cpf", "00189004967", False) == "***.***.***-67"
