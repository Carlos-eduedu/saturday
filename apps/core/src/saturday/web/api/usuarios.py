"""Aba Usuários do painel (`/admin/gestao/usuarios`), só para gestor.

Cadastrar, editar, redefinir senha, desbloquear, desativar e reativar; nunca
apagar (decisão 0012). As regras ficam em `painel/usuarios.py`; aqui só HTTP.
`GET /admin/usuarios` continua sendo a lista de transferir, para qualquer perfil.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Conversa, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import usuarios as regras
from saturday.painel.acoes import AcaoRecusada
from saturday.painel.sessoes import agora
from saturday.web.dependencies import (
    UsuarioLogado,
    exigir_fabrica,
    gestor_com_csrf,
    gestor_logado,
)

router = APIRouter(prefix="/admin/gestao/usuarios", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Gestor = Annotated[UsuarioLogado, Depends(gestor_logado)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]


class NovoUsuario(BaseModel):
    nome: str
    email: str
    perfil: str
    senha: str


class Edicao(BaseModel):
    nome: str | None = None
    email: str | None = None
    perfil: str | None = None


class NovaSenha(BaseModel):
    senha: str


def _executar(fabrica: sessionmaker[Session], acao: Callable[[Session], Any]) -> Any:
    try:
        with abrir_sessao(fabrica) as sessao:
            return acao(sessao)
    except AcaoRecusada as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detalhe) from exc


def _linha(usuario: UsuarioPainel, assumidas: int) -> dict[str, Any]:
    ate = usuario.bloqueado_ate
    if ate is not None and ate <= agora():
        ate = None
    situacao = "desativado" if not usuario.ativo else "bloqueado" if ate else "ativo"
    return {
        "id": str(usuario.id),
        "nome": usuario.nome,
        "email": usuario.email,
        "perfil": usuario.perfil,
        "situacao": situacao,
        "bloqueado_ate": ate.isoformat() if ate else None,
        "criado_em": usuario.criado_em.isoformat(),
        "conversas_assumidas": assumidas,
    }


@router.get("")
def listar(_usuario: Gestor, fabrica: Fabrica) -> list[dict[str, Any]]:
    """Ativos primeiro, por nome; desativados no fim."""

    with abrir_sessao(fabrica) as sessao:
        usuarios = sessao.scalars(
            select(UsuarioPainel).order_by(UsuarioPainel.ativo.desc(), UsuarioPainel.nome)
        ).all()
        assumidas = dict(
            sessao.execute(
                select(Conversa.atendente_id, func.count())
                .where(Conversa.atendimento == "assumida")
                .group_by(Conversa.atendente_id)
            ).all()
        )
        return [_linha(u, int(assumidas.get(u.id, 0))) for u in usuarios]


@router.post("", status_code=201)
def criar(dados: NovoUsuario, usuario: GestorCsrf, fabrica: Fabrica) -> dict[str, str]:
    novo = _executar(
        fabrica,
        lambda s: regras.criar(s, usuario.id, dados.nome, dados.email, dados.perfil, dados.senha),
    )
    return {"id": str(novo.id)}


@router.patch("/{usuario_id}", status_code=204)
def editar(usuario_id: uuid.UUID, dados: Edicao, usuario: GestorCsrf, fabrica: Fabrica) -> Response:
    _executar(
        fabrica,
        lambda s: regras.editar(
            s, usuario.id, usuario_id, nome=dados.nome, email=dados.email, perfil=dados.perfil
        ),
    )
    return Response(status_code=204)


@router.post("/{usuario_id}/senha", status_code=204)
def redefinir_senha(
    usuario_id: uuid.UUID, dados: NovaSenha, usuario: GestorCsrf, fabrica: Fabrica
) -> Response:
    _executar(fabrica, lambda s: regras.redefinir_senha(s, usuario.id, usuario_id, dados.senha))
    return Response(status_code=204)


@router.post("/{usuario_id}/desbloquear", status_code=204)
def desbloquear(usuario_id: uuid.UUID, usuario: GestorCsrf, fabrica: Fabrica) -> Response:
    _executar(fabrica, lambda s: regras.desbloquear(s, usuario.id, usuario_id))
    return Response(status_code=204)


@router.post("/{usuario_id}/desativar")
def desativar(usuario_id: uuid.UUID, usuario: GestorCsrf, fabrica: Fabrica) -> dict[str, int]:
    devolvidas = _executar(fabrica, lambda s: regras.desativar(s, usuario.id, usuario_id))
    return {"conversas_devolvidas": devolvidas}


@router.post("/{usuario_id}/reativar", status_code=204)
def reativar(usuario_id: uuid.UUID, usuario: GestorCsrf, fabrica: Fabrica) -> Response:
    _executar(fabrica, lambda s: regras.reativar(s, usuario.id, usuario_id))
    return Response(status_code=204)
