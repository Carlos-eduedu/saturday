"""Rotas de monitoramento."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["monitoring"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
