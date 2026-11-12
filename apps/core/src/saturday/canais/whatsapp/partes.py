"""Divisão do texto em partes, como a Meta espera.

Um texto livre vai numa mensagem por bloco separado por linha em branco, no
máximo cinco partes. Acima de 4096 caracteres a própria Meta recusa, então cada
parte é fatiada também por tamanho.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from saturday.dados import outbox as fila
from saturday.dados import repositorios
from saturday.dados.modelos import Outbox
from saturday.dados.sessao import sessao as abrir_sessao

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


def enviar_em_partes(
    fabrica: sessionmaker[Session],
    linha: Outbox,
    texto: str,
    enviar: Callable[[str], str | None],
) -> None:
    """Envia as partes que faltam e grava o progresso a cada uma.

    Sem isso, uma falha na parte 3 faria a nova tentativa repetir as partes 1 e
    2 no celular do cliente. ``enviar`` devolve o id da mensagem no provedor.
    """

    payload = linha.payload or {}
    partes = dividir(texto)
    inicio = int(payload.get("partes_enviadas") or 0)
    for indice in range(inicio, len(partes)):
        if indice > inicio:
            time.sleep(INTERVALO_ENTRE_PARTES_S)
        wamid = enviar(partes[indice])
        with abrir_sessao(fabrica) as sessao:
            fila.registrar_partes_enviadas(sessao, linha.id, indice + 1)
            mensagem_id = payload.get("mensagem_id")
            # O id da primeira parte identifica a mensagem nos status.
            if indice == 0 and isinstance(mensagem_id, int):
                repositorios.marcar_envio(sessao, mensagem_id, wamid=wamid, status="sent")
