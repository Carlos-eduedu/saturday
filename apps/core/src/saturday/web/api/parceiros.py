"""Aba Integrações do painel: os parceiros que o Saturday chama, só leitura."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from saturday.painel.parceiros import parceiros
from saturday.web.dependencies import UsuarioLogado, gestor_logado, get_settings

router = APIRouter(prefix="/admin/gestao/parceiros", tags=["painel"])


@router.get("")
def listar(
    request: Request, _usuario: Annotated[UsuarioLogado, Depends(gestor_logado)]
) -> list[dict[str, Any]]:
    return parceiros(get_settings(request))
