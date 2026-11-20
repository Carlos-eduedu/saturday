"""Página Integrações do painel (decisão 0035): só o gestor gera e revoga tokens."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
    get_settings,
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
        "webhook_url": i.webhook_url,
        "tem_segredo": i.webhook_segredo is not None,
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


# ------------------------------------------------------------------ webhook (fase 2)


class Webhook(BaseModel):
    url: str | None = Field(default=None, max_length=2000)


def _recusa(exc: integracoes.IntegracaoRecusada) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detalhe)


@router.put("/{integracao_id}/webhook", status_code=204)
def definir_webhook(
    integracao_id: uuid.UUID,
    dados: Webhook,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
) -> Response:
    url = (dados.url or "").strip() or None
    local = get_settings(request).environment not in ("homolog", "prod")
    if url is not None and not integracoes.url_aceita(url, local=local):
        raise HTTPException(status_code=422, detail="o endereço precisa começar com https://")
    with abrir_sessao(fabrica) as sessao:
        try:
            integracoes.definir_webhook(sessao, integracao_id, url, usuario.id)
        except integracoes.IntegracaoRecusada as exc:
            raise _recusa(exc) from exc
    return Response(status_code=204)


@router.post("/{integracao_id}/webhook/segredo")
def gerar_segredo(
    integracao_id: uuid.UUID, usuario: GestorCsrf, fabrica: Fabrica
) -> dict[str, str]:
    """Devolve o segredo uma única vez; o anterior deixa de valer."""

    with abrir_sessao(fabrica) as sessao:
        try:
            return {"segredo": integracoes.gerar_segredo(sessao, integracao_id, usuario.id)}
        except integracoes.IntegracaoRecusada as exc:
            raise _recusa(exc) from exc


@router.get("/{integracao_id}/webhook/entregas")
def entregas(integracao_id: uuid.UUID, _usuario: Gestor, fabrica: Fabrica) -> list[dict[str, Any]]:
    with abrir_sessao(fabrica) as sessao:
        return [
            {
                "id": e.id,
                "tipo": e.payload.get("tipo"),
                "status": (e.payload.get("evento") or {}).get("status"),
                "situacao": "entregue"
                if e.entregue_em
                else "desistiu"
                if e.falhou_em
                else "pendente",
                "tentativas": e.tentativas,
                "criada_em": e.criada_em.isoformat(),
                "entregue_em": e.entregue_em.isoformat() if e.entregue_em else None,
            }
            for e in integracoes.entregas(sessao, integracao_id)
        ]
