"""Rotas de conversa (gerenciamento)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/conversations", tags=["conversas"])
