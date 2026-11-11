"""Cota de consultas por parceiro (regra 5 do AGENTS.md).

A reserva acontece antes da chamada e não volta em erro incerto: num timeout,
a Granatech pode ter aberto a consulta e cobrado. Só um erro comprovado do
nosso lado (4xx) devolve a reserva.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados import repositorios
from saturday.dados.modelos import Cota
from saturday.dados.trava import chave_trava

LIMIAR_ALERTA = 0.8


class CotaEsgotada(Exception):
    """Sem cota para abrir consulta hoje (``diaria``) ou neste mês (``mensal``)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(f"cota {motivo} esgotada")
        self.motivo = motivo


def reservar(
    sessao: Session,
    *,
    parceiro: str,
    hoje: date,
    teto_dia: int,
    teto_mes: int,
) -> None:
    """Gasta uma consulta da cota ou levanta ``CotaEsgotada``.

    A trava consultiva serializa as reservas do parceiro até o commit: sem ela,
    dois workers leriam o mesmo total e passariam juntos do teto.
    """

    sessao.execute(
        text("SELECT pg_advisory_xact_lock(:chave)"),
        {"chave": chave_trava(f"cota:{parceiro}")},
    )
    base = select(func.coalesce(func.sum(Cota.usadas), 0)).where(Cota.parceiro == parceiro)
    no_mes = int(sessao.scalar(base.where(Cota.dia >= hoje.replace(day=1))) or 0)
    no_dia = int(sessao.scalar(base.where(Cota.dia == hoje)) or 0)
    if no_dia >= teto_dia:
        raise CotaEsgotada("diaria")
    if no_mes >= teto_mes:
        raise CotaEsgotada("mensal")

    sessao.execute(
        insert(Cota)
        .values(parceiro=parceiro, dia=hoje, usadas=1)
        .on_conflict_do_update(index_elements=["parceiro", "dia"], set_={"usadas": Cota.usadas + 1})
    )
    limiar = teto_mes * LIMIAR_ALERTA
    if no_mes < limiar <= no_mes + 1:
        repositorios.abrir_alerta(
            sessao,
            "cota_80",
            detalhe={"parceiro": parceiro, "usadas": no_mes + 1, "teto": teto_mes},
        )


def devolver(sessao: Session, *, parceiro: str, dia: date) -> None:
    sessao.execute(
        update(Cota)
        .where(Cota.parceiro == parceiro, Cota.dia == dia, Cota.usadas > 0)
        .values(usadas=Cota.usadas - 1)
    )
