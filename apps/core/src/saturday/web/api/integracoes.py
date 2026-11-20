"""Página Integrações do painel (decisão 0035): só o gestor gera e revoga tokens."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Integracao, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import integracoes
from saturday.web.dependencies import (
    UsuarioLogado,
    gestor_com_csrf,
    gestor_logado,
    get_fabrica,
)

router = APIRouter(prefix="/admin/gestao/integracoes", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Gestor = Annotated[UsuarioLogado, Depends(gestor_logado)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]

Escopo = Literal["leitura", "revelar", "acoes", "operacoes", "homologacao"]


class NovaIntegracao(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    escopos: list[Escopo] = Field(min_length=1)


def _linha(i: Integracao, criada_por: str | None) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "nome": i.nome,
        "escopos": i.escopos,
        "criada_por": criada_por,
        "criada_em": i.criada_em.isoformat(),
        "revogada_em": i.revogada_em.isoformat() if i.revogada_em else None,
        "ultimo_uso_em": i.ultimo_uso_em.isoformat() if i.ultimo_uso_em else None,
    }


@router.get("")
def listar(_usuario: Gestor, fabrica: Fabrica) -> list[dict[str, Any]]:
    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.execute(
            select(Integracao, UsuarioPainel.nome)
            .outerjoin(UsuarioPainel, UsuarioPainel.id == Integracao.criada_por)
            .order_by(Integracao.revogada_em.is_not(None), Integracao.criada_em.desc())
        ).all()
        return [_linha(i, nome) for i, nome in linhas]


@router.post("", status_code=201)
def criar(dados: NovaIntegracao, usuario: GestorCsrf, fabrica: Fabrica) -> dict[str, Any]:
    """Devolve o token uma única vez; depois só o hash existe."""

    with abrir_sessao(fabrica) as sessao:
        linha, token = integracoes.criar(sessao, dados.nome, list(dados.escopos), usuario.id)
        return {**_linha(linha, usuario.nome), "token": token}


@router.post("/{integracao_id}/revogar", status_code=204)
def revogar(integracao_id: uuid.UUID, usuario: GestorCsrf, fabrica: Fabrica) -> Response:
    with abrir_sessao(fabrica) as sessao:
        if not integracoes.revogar(sessao, integracao_id, usuario.id):
            raise HTTPException(status_code=404, detail="integração não encontrada ou já revogada")
    return Response(status_code=204)
