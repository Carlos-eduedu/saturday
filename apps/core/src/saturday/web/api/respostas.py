"""Respostas rápidas do painel: textos salvos que o atendente insere com "/".

Todos leem; só o gestor cria, edita e apaga, com CSRF e auditoria. O texto é
fixo e quem envia é o atendente, depois de revisar: nada passa pela IA.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import RespostaRapida
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel.auditoria import auditar
from saturday.web.dependencies import (
    UsuarioLogado,
    exigir_fabrica,
    gestor_com_csrf,
    usuario_logado,
)

router = APIRouter(prefix="/admin/respostas-rapidas", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]

ATALHO = r"^[a-z0-9][a-z0-9_-]{0,39}$"


class Resposta(BaseModel):
    atalho: str = Field(pattern=ATALHO)
    texto: str = Field(min_length=1, max_length=4096)


def _linha(r: RespostaRapida) -> dict[str, Any]:
    return {"id": r.id, "atalho": r.atalho, "texto": r.texto}


def _gravar(fabrica: sessionmaker[Session], acao: Any) -> dict[str, Any]:
    try:
        with abrir_sessao(fabrica) as sessao:
            return acao(sessao)  # type: ignore[no-any-return]
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="já existe uma resposta com esse atalho"
        ) from exc


@router.get("")
def listar(_usuario: Logado, fabrica: Fabrica) -> list[dict[str, Any]]:
    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.scalars(select(RespostaRapida).order_by(RespostaRapida.atalho)).all()
        return [_linha(r) for r in linhas]


@router.post("", status_code=201)
def criar(dados: Resposta, usuario: GestorCsrf, fabrica: Fabrica) -> dict[str, Any]:
    def acao(sessao: Session) -> dict[str, Any]:
        linha = RespostaRapida(atalho=dados.atalho, texto=dados.texto, criado_por=usuario.id)
        sessao.add(linha)
        sessao.flush()
        auditar(sessao, usuario.id, "resposta_rapida:criar", str(linha.id))
        return _linha(linha)

    return _gravar(fabrica, acao)


@router.patch("/{resposta_id}")
def editar(
    resposta_id: int, dados: Resposta, usuario: GestorCsrf, fabrica: Fabrica
) -> dict[str, Any]:
    def acao(sessao: Session) -> dict[str, Any]:
        linha = sessao.get(RespostaRapida, resposta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="resposta não encontrada")
        linha.atalho, linha.texto = dados.atalho, dados.texto
        sessao.flush()
        auditar(sessao, usuario.id, "resposta_rapida:editar", str(linha.id))
        return _linha(linha)

    return _gravar(fabrica, acao)


@router.delete("/{resposta_id}", status_code=204)
def apagar(resposta_id: int, usuario: GestorCsrf, fabrica: Fabrica) -> Response:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(RespostaRapida, resposta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="resposta não encontrada")
        sessao.delete(linha)
        auditar(sessao, usuario.id, "resposta_rapida:apagar", str(resposta_id))
    return Response(status_code=204)
