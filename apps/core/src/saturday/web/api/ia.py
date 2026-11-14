"""Trilha da IA por conversa e custos (plano de custos e trilha).

A trilha é para todos os usuários do painel; custo e tokens só para gestor
(para atendente, esses campos voltam vazios). Valores em US$, como a
OpenRouter cobra.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Conversa, Turno
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import MASCARAS
from saturday.settings import TZ_OPERACAO
from saturday.web.api.canais import Gestor
from saturday.web.dependencies import UsuarioLogado, exigir_fabrica, usuario_logado

router = APIRouter(prefix="/admin", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]

LIMITE_TURNOS = 100
CAMPOS_DE_CUSTO = ("custo_usd", "tokens_entrada", "tokens_saida")


def _sem_custo(chamada: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if k in CAMPOS_DE_CUSTO else v) for k, v in chamada.items()}


@router.get("/conversas/{conversa_id}/turnos")
def turnos(conversa_id: uuid.UUID, usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        if sessao.get(Conversa, conversa_id) is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        linhas = sessao.scalars(
            select(Turno)
            .where(Turno.conversa_id == conversa_id)
            .order_by(Turno.criado_em.desc(), Turno.id.desc())
            .limit(LIMITE_TURNOS)
        ).all()
        total = sessao.execute(
            select(
                func.coalesce(func.sum(Turno.custo_usd), 0),
                func.coalesce(func.sum(Turno.tokens), 0),
            ).where(Turno.conversa_id == conversa_id)
        ).one()

    gestor = usuario.gestor
    return {
        "custo_usd": float(total[0]) if gestor else None,
        "tokens": int(total[1]) if gestor else None,
        "turnos": [turno_json(t, gestor) for t in linhas],
    }


def turno_json(t: Turno, gestor: bool) -> dict[str, Any]:
    """Um turno para o painel; custo e tokens só para gestor."""

    return {
        "id": t.id,
        "criado_em": t.criado_em,
        "caminho": t.caminho,
        "status": t.status,
        "motivo": t.motivo,
        "etapa": t.etapa,
        "classificacao": t.classificacao,
        "chamadas": t.chamadas if gestor else [_sem_custo(c) for c in t.chamadas],
        "custo_usd": t.custo_usd if gestor else None,
        "tokens": t.tokens if gestor else None,
        "duracao_ms": t.duracao_ms,
        "erro": t.erro,
    }


@router.get("/custos")
def custos(
    _usuario: Gestor,
    fabrica: Fabrica,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """Totais por dia do período (padrão: mês corrente) e as conversas mais caras."""

    fuso = ZoneInfo(TZ_OPERACAO)
    hoje = datetime.now(fuso).date()
    inicio_dia = de or hoje.replace(day=1)
    fim_dia = ate or hoje
    if fim_dia < inicio_dia:
        raise HTTPException(status_code=422, detail="período invertido")
    inicio = datetime.combine(inicio_dia, datetime.min.time(), fuso).astimezone(UTC)
    fim = datetime.combine(fim_dia + timedelta(days=1), datetime.min.time(), fuso).astimezone(UTC)

    dia = cast(func.timezone(TZ_OPERACAO, Turno.criado_em), Date)
    periodo = (Turno.criado_em >= inicio, Turno.criado_em < fim)
    with abrir_sessao(fabrica) as sessao:
        por_dia = sessao.execute(
            select(dia, func.sum(Turno.custo_usd), func.sum(Turno.tokens), func.count())
            .where(*periodo)
            .group_by(dia)
            .order_by(dia)
        ).all()
        caras = sessao.execute(
            select(
                Conversa.id,
                Conversa.telefone,
                Conversa.canal,
                func.sum(Turno.custo_usd).label("custo"),
            )
            .join(Turno, Turno.conversa_id == Conversa.id)
            .where(*periodo)
            .group_by(Conversa.id)
            .order_by(func.sum(Turno.custo_usd).desc())
            .limit(10)
        ).all()

    dias = [
        {"dia": d, "custo_usd": float(c or 0), "tokens": int(t or 0), "turnos": int(n)}
        for d, c, t, n in por_dia
    ]
    return {
        "de": inicio_dia,
        "ate": fim_dia,
        "total": {
            "custo_usd": sum(d["custo_usd"] for d in dias),
            "tokens": sum(d["tokens"] for d in dias),
            "turnos": sum(d["turnos"] for d in dias),
        },
        "hoje": next((d for d in dias if d["dia"] == hoje), None),
        "dias": dias,
        "conversas_mais_caras": [
            {
                "id": str(cid),
                "telefone": MASCARAS["telefone"](tel) if tel else None,
                "canal": canal,
                "custo_usd": float(custo or 0),
            }
            for cid, tel, canal, custo in caras
        ],
    }
