"""Janela de 24 h da conversa.

A Meta aceita texto livre só até 24 h depois da última mensagem do cliente.
Fora da janela, só modelo aprovado — texto livre é recusado com o código 131047.
"""

from __future__ import annotations

from datetime import datetime, timedelta

JANELA = timedelta(hours=24)


def janela_aberta(ultima_entrada_em: datetime | None, agora: datetime) -> bool:
    """Aberta quando o cliente escreveu nas últimas 24 h.

    Sem mensagem do cliente não há conversa iniciada por ele: a janela fica
    fechada, e o primeiro contato tem que ser por modelo.
    """

    if ultima_entrada_em is None:
        return False
    return agora - ultima_entrada_em < JANELA


def expira_em(ultima_entrada_em: datetime | None) -> datetime | None:
    """Quando a janela fecha, para o painel mostrar o tempo restante."""

    if ultima_entrada_em is None:
        return None
    return ultima_entrada_em + JANELA
