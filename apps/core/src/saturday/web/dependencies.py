"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import sessoes
from saturday.settings import Settings

COOKIE_SESSAO = "saturday_sessao"

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_agent_service(request: Request) -> AgentService:
    """Devolve o serviço criado no lifespan (ou substituído em testes)."""

    return cast(AgentService, request.app.state.agent_service)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_fabrica(request: Request) -> sessionmaker[Session] | None:
    """Fábrica de sessões. ``None`` em `pytest`, onde não há Postgres."""

    return cast("sessionmaker[Session] | None", getattr(request.app.state, "fabrica", None))


def verificar_api_key(
    request: Request,
    recebida: Annotated[str | None, Security(api_key_header)] = None,
) -> None:
    """Valida o header ``X-API-Key`` quando a chave está configurada."""

    settings = cast(Settings, request.app.state.settings)
    esperada = settings.api_key.get_secret_value()
    if not esperada:
        if settings.environment == "prod":
            raise HTTPException(status_code=401, detail="não autorizado")
        return

    if recebida is None or not secrets.compare_digest(recebida.encode(), esperada.encode()):
        raise HTTPException(status_code=401, detail="não autorizado")


def exigir_fabrica(request: Request) -> sessionmaker[Session]:
    """O painel não existe sem Postgres: estado de atendimento mora lá."""

    fabrica = get_fabrica(request)
    if fabrica is None:
        raise HTTPException(status_code=503, detail="painel indisponível sem banco")
    return fabrica


@dataclass(frozen=True)
class UsuarioLogado:
    id: uuid.UUID
    email: str
    nome: str
    perfil: str
    token: str

    @property
    def gestor(self) -> bool:
        return self.perfil == "gestor"


def usuario_logado(
    fabrica: Annotated[sessionmaker[Session], Depends(exigir_fabrica)],
    token: Annotated[str | None, Cookie(alias=COOKIE_SESSAO)] = None,
) -> UsuarioLogado:
    if not token:
        raise HTTPException(status_code=401, detail="não autenticado")
    with abrir_sessao(fabrica) as sessao:
        usuario = sessoes.usuario_da_sessao(sessao, token)
        if usuario is None:
            raise HTTPException(status_code=401, detail="não autenticado")
        return UsuarioLogado(usuario.id, usuario.email, usuario.nome, usuario.perfil, token)


def exigir_csrf(
    request: Request,
    usuario: Annotated[UsuarioLogado, Depends(usuario_logado)],
    recebido: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> UsuarioLogado:
    """Toda ação que muda estado confere o CSRF da sessão."""

    segredo = get_settings(request).sessao_segredo.get_secret_value()
    if not sessoes.csrf_confere(segredo, usuario.token, recebido):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    return usuario


def _gestor(usuario: UsuarioLogado) -> UsuarioLogado:
    if not usuario.gestor:
        raise HTTPException(status_code=403, detail="só gestor")
    return usuario


def gestor_logado(usuario: Annotated[UsuarioLogado, Depends(usuario_logado)]) -> UsuarioLogado:
    """Telas de gestão (Canais, Usuários): só leitura."""

    return _gestor(usuario)


def gestor_com_csrf(usuario: Annotated[UsuarioLogado, Depends(exigir_csrf)]) -> UsuarioLogado:
    """Telas de gestão (Canais, Usuários): ações que mudam estado."""

    return _gestor(usuario)
