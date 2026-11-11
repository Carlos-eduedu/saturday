"""Divisão do texto em partes, como a Meta espera.

Um texto livre vai numa mensagem por bloco separado por linha em branco, no
máximo cinco partes. Acima de 4096 caracteres a própria Meta recusa, então cada
parte é fatiada também por tamanho.
"""

from __future__ import annotations

import re

MAX_PARTES = 5
MAX_CARACTERES = 4000
INTERVALO_ENTRE_PARTES_S = 0.9

_SEPARADOR = re.compile(r"\n\s*\n")


def _fatiar(texto: str) -> list[str]:
    """Quebra um bloco grande demais, preferindo fim de linha."""

    if len(texto) <= MAX_CARACTERES:
        return [texto]

    pedacos: list[str] = []
    restante = texto
    while len(restante) > MAX_CARACTERES:
        corte = restante.rfind("\n", 0, MAX_CARACTERES)
        if corte <= 0:
            corte = restante.rfind(" ", 0, MAX_CARACTERES)
        if corte <= 0:
            corte = MAX_CARACTERES
        pedacos.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if restante:
        pedacos.append(restante)
    return pedacos


def dividir(texto: str) -> list[str]:
    """Divide por linha em branco, respeitando o teto de cinco partes.

    O que passa de cinco blocos não é descartado: entra na última parte, para
    nenhuma informação do cliente sumir.
    """

    blocos = [bloco.strip() for bloco in _SEPARADOR.split(texto) if bloco.strip()]
    if not blocos:
        return []

    if len(blocos) > MAX_PARTES:
        blocos = [*blocos[: MAX_PARTES - 1], "\n\n".join(blocos[MAX_PARTES - 1 :])]

    return [pedaco for bloco in blocos for pedaco in _fatiar(bloco)]
