"""Rotas de conversa (gerenciamento)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from saturday.web.dependencies import verificar_api_key

router = APIRouter(
    prefix="/conversations",
    tags=["conversas"],
    dependencies=[Depends(verificar_api_key)],
)
