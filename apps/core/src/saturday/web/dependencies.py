"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import integracoes, membros, sessoes
from saturday.settings import Settings

COOKIE_SESSAO = "saturday_sessao"
# Recusa de quem tem a troca de senha pendente (decisão 0030). O painel nem
# chega a recebê-la: lê `trocar_senha` em `GET /admin/eu` e mostra só a troca.
TROCA_PENDENTE = "troque a senha para continuar"

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_agent_service(request: Request) -> AgentService:
    """Devolve o serviço criado no lifespan (ou substituído em testes)."""

    return cast(AgentService, request.app.state.agent_service)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_fabrica(request: Request) -> sessionmaker[Session]:
    """Fábrica de sessões: a subida sempre a cria (decisão 0022)."""

    return cast("sessionmaker[Session]", request.app.state.fabrica)


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


@dataclass(frozen=True)
class UsuarioLogado:
    id: uuid.UUID
    email: str
    nome: str
    perfil: str
    token: str
    # Troca modelos e a base de conhecimento na aba Agente; independe do perfil.
    pode_editar_agente: bool = False
    # Perfil (seção "Você"): telefone e a chave da foto no storage.
    telefone: str | None = None
    foto_chave: str | None = None
    pode_testar_fluxos: bool = False
    cargo: str | None = None
    disponivel: bool = True
    # Troca de senha obrigatória pendente (decisão 0030).
    trocar_senha: bool = False

    @property
    def gestor(self) -> bool:
        return self.perfil == "gestor"


def sessao_aberta(
    fabrica: Annotated[sessionmaker[Session], Depends(get_fabrica)],
    token: Annotated[str | None, Cookie(alias=COOKIE_SESSAO)] = None,
) -> UsuarioLogado:
    """Quem tem sessão válida, mesmo com a troca de senha pendente.

    Só para o mínimo da tela de troca (quem sou eu, trocar a senha e sair);
    todo o resto usa `usuario_logado`.
    """

    if not token:
        raise HTTPException(status_code=401, detail="não autenticado")
    with abrir_sessao(fabrica) as sessao:
        usuario = sessoes.usuario_da_sessao(sessao, token)
        if usuario is None:
            raise HTTPException(status_code=401, detail="não autenticado")
        membros.marcar_acesso(usuario, sessoes.agora())
        return UsuarioLogado(
            usuario.id,
            usuario.email,
            usuario.nome,
            usuario.perfil,
            token,
            usuario.pode_editar_agente,
            usuario.telefone,
            usuario.foto_chave,
            usuario.pode_testar_fluxos,
            usuario.cargo,
            usuario.disponivel,
            usuario.trocar_senha,
        )


def usuario_logado(usuario: Annotated[UsuarioLogado, Depends(sessao_aberta)]) -> UsuarioLogado:
    """Sessão válida e sem troca de senha pendente: a porta de todo o `/admin`."""

    if usuario.trocar_senha:
        raise HTTPException(status_code=403, detail=TROCA_PENDENTE)
    return usuario


def _conferir_csrf(request: Request, usuario: UsuarioLogado, recebido: str | None) -> UsuarioLogado:
    segredo = get_settings(request).sessao_segredo.get_secret_value()
    if not sessoes.csrf_confere(segredo, usuario.token, recebido):
        raise HTTPException(status_code=403, detail="CSRF inválido")
    return usuario


def exigir_csrf(
    request: Request,
    usuario: Annotated[UsuarioLogado, Depends(usuario_logado)],
    recebido: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> UsuarioLogado:
    """Toda ação que muda estado confere o CSRF da sessão."""

    return _conferir_csrf(request, usuario, recebido)


def sessao_aberta_com_csrf(
    request: Request,
    usuario: Annotated[UsuarioLogado, Depends(sessao_aberta)],
    recebido: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> UsuarioLogado:
    """CSRF para trocar a senha e sair, que valem com a troca pendente."""

    return _conferir_csrf(request, usuario, recebido)


def _gestor(usuario: UsuarioLogado) -> UsuarioLogado:
    if not usuario.gestor:
        raise HTTPException(status_code=403, detail="só gestor")
    return usuario


def gestor_logado(usuario: Annotated[UsuarioLogado, Depends(usuario_logado)]) -> UsuarioLogado:
    """Telas de gestão (Canais, Usuários): só leitura."""

    return _gestor(usuario)


def editor_do_agente(usuario: Annotated[UsuarioLogado, Depends(exigir_csrf)]) -> UsuarioLogado:
    """Aba Agente: salvar e restaurar a configuração, atualizar o catálogo."""

    if not usuario.pode_editar_agente:
        raise HTTPException(status_code=403, detail="sem permissão para editar o agente")
    return usuario


def gestor_com_csrf(usuario: Annotated[UsuarioLogado, Depends(exigir_csrf)]) -> UsuarioLogado:
    """Telas de gestão (Canais, Usuários): ações que mudam estado."""

    return _gestor(usuario)


@dataclass(frozen=True)
class IntegracaoLogada:
    id: uuid.UUID
    nome: str


def integracao(escopo: str) -> Callable[..., IntegracaoLogada]:
    """Dependência do proxy (decisão 0035): `Authorization: Bearer` com o escopo."""

    def conferir(
        request: Request, authorization: Annotated[str | None, Header()] = None
    ) -> IntegracaoLogada:
        esquema, _, token = (authorization or "").partition(" ")
        if esquema.lower() != "bearer":
            token = ""
        with abrir_sessao(get_fabrica(request)) as sessao:
            try:
                linha = integracoes.autenticar(sessao, token.strip(), escopo, datetime.now(UTC))
            except integracoes.IntegracaoRecusada as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detalhe) from exc
            return IntegracaoLogada(id=linha.id, nome=linha.nome)

    return conferir
