"""Proxy da Granatech para o APP MEX (decisão 0035), fase 1: só leitura.

O APP MEX fala no formato da Granatech: as rotas abaixo repetem as dela, e o
corpo volta cru. O Saturday troca o token da integração pelo login da MEX. Só
as rotas desta lista passam; o resto é 404. Escrita (consulta, termo,
simulação, proposta) entra na fase 3, com cota, teto e `Idempotency-Key`.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import CONSIGNADO, ClienteGranatech, ErroGranatech
from saturday.dados.modelos import ConsultaGranatech
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel.auditoria import auditar
from saturday.web.api.admin import cota_da_granatech
from saturday.web.dependencies import (
    IntegracaoLogada,
    get_agent_service,
    get_fabrica,
    get_settings,
    integracao,
)

router = APIRouter(prefix="/integracao", tags=["integracao"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Leitura = Annotated[IntegracaoLogada, Depends(integracao("leitura"))]
Revelar = Annotated[IntegracaoLogada, Depends(integracao("revelar"))]
# Id da Granatech no caminho: sem `/`, `..` nem `?`, para não sair da lista de rotas.
Id = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def get_granatech(request: Request) -> ClienteGranatech:
    cliente = get_agent_service(request).context.granatech
    if cliente is None:
        raise HTTPException(status_code=503, detail="Granatech desligada")
    return cliente


Granatech = Annotated[ClienteGranatech, Depends(get_granatech)]


def _repassar(
    cliente: ClienteGranatech, rota_modelo: str, caminho: str, request: Request
) -> JSONResponse:
    try:
        status, corpo = cliente.repassar(
            "GET",
            f"{CONSIGNADO}{rota_modelo}",
            f"{CONSIGNADO}{caminho}",
            # Lista de pares: chave repetida (`?status=a&status=b`) passa inteira.
            httpx.QueryParams(request.url.query) or None,
        )
    except ErroGranatech as exc:
        raise HTTPException(status_code=502, detail="Granatech indisponível") from exc
    return JSONResponse(status_code=status, content=corpo)


# ------------------------------------------------------------------ proxy (leitura)

GRANATECH = f"/granatech{CONSIGNADO}"


@router.get(f"{GRANATECH}/consulta-saldo/usuario")
def consultas(request: Request, _i: Leitura, cliente: Granatech) -> JSONResponse:
    return _repassar(cliente, "/consulta-saldo/usuario", "/consulta-saldo/usuario", request)


@router.get(f"{GRANATECH}/consulta-saldo/{{id_consulta}}")
def consulta(id_consulta: Id, request: Request, _i: Leitura, cliente: Granatech) -> JSONResponse:
    return _repassar(cliente, "/consulta-saldo/{id}", f"/consulta-saldo/{id_consulta}", request)


@router.get(f"{GRANATECH}/bancos")
def bancos(request: Request, _i: Leitura, cliente: Granatech) -> JSONResponse:
    return _repassar(cliente, "/bancos", "/bancos", request)


@router.get(f"{GRANATECH}/propostas/lista")
def propostas(request: Request, _i: Leitura, cliente: Granatech) -> JSONResponse:
    return _repassar(cliente, "/propostas/lista", "/propostas/lista", request)


@router.get(f"{GRANATECH}/propostas/{{id_proposta}}")
def proposta(id_proposta: Id, request: Request, _i: Leitura, cliente: Granatech) -> JSONResponse:
    return _repassar(cliente, "/propostas/{id}", f"/propostas/{id_proposta}", request)


# ------------------------------------------------------------------ rotas do Saturday


@router.get("/cota")
def cota(request: Request, _i: Leitura, fabrica: Fabrica) -> dict[str, Any]:
    return cota_da_granatech(get_settings(request), fabrica)


@router.post("/consultas/{id_consulta}/revelar")
def revelar_cpf(id_consulta: Id, quem: Revelar, fabrica: Fabrica) -> dict[str, str]:
    """CPF da consulta pelo id da Granatech, o único que o APP MEX conhece."""

    with abrir_sessao(fabrica) as sessao:
        cpf = sessao.scalar(
            select(ConsultaGranatech.cpf).where(
                ConsultaGranatech.id_externo == id_consulta,
                ConsultaGranatech.teste.is_(False),
            )
        )
        if cpf is None:
            raise HTTPException(status_code=404, detail="consulta não encontrada")
        # Na mesma transação: sem a linha de auditoria, o dado não sai.
        auditar(
            sessao,
            None,
            "revelar:cpf",
            f"consulta:{id_consulta}",
            {"origem": "integracao", "integracao": str(quem.id)},
        )
    return {"campo": "cpf", "valor": cpf}
