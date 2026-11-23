"""Erros para o Sentry, sem dado pessoal (decisão 0038)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from saturday.privacidade import mascarar_texto
from saturday.settings import Settings

if TYPE_CHECKING:
    from sentry_sdk._types import Breadcrumb, BreadcrumbHint, Event, Hint

logger = logging.getLogger(__name__)

# A query da consulta da Granatech leva CPF, nome e telefone (como no access log).
# Vale para URL inteira e caminho relativo.
_QUERY_DE_URL = re.compile(r"(/[^\s?#\"']*)\?[^\s#\"']*")
# Um CPF ou telefone passado como número ao log chega como `int` nos params.
_MENOR_NUMERO_LONGO = 10**9


def iniciar_sentry(settings: Settings) -> bool:
    """Liga o Sentry quando há DSN; nunca nos testes. Devolve se ligou."""

    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn or settings.environment == "pytest":
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        # Só o que está listado: as integrações automáticas de IA, httpx e banco
        # gravam prompt, URL com CPF e SQL.
        auto_enabling_integrations=False,
        integrations=[
            # `logger.error`/`exception` vira evento: quase todo erro é pego e logado.
            LoggingIntegration(
                level=None, event_level=logging.ERROR, breadcrumb_level=logging.WARNING
            ),
        ],
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "off"}},
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "gen_ai": {"inputs": False, "outputs": False},
            "database_query_data": False,
            # Os frames carregam CPF, telefone e o texto da mensagem.
            "stack_frame_variables": False,
        },
        before_send=limpar_evento,
        before_breadcrumb=_limpar_breadcrumb,
    )
    # Prova no log de que o DSN chegou, sem mostrá-lo (decisão 0005).
    logger.info("sentry_ligado ambiente=%s", settings.environment)
    return True


def limpar_evento(evento: Event, _hint: Hint) -> Event:
    """Mascara todo texto do evento ou breadcrumb e corta a query das URLs."""

    limpo: Event = _limpar(evento)
    return limpo


def _limpar_breadcrumb(breadcrumb: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb:
    limpo: Breadcrumb = _limpar(breadcrumb)
    return limpo


def _limpar(valor: Any) -> Any:
    if isinstance(valor, str):
        return mascarar_texto(_QUERY_DE_URL.sub(r"\1", valor))
    if isinstance(valor, int) and abs(valor) >= _MENOR_NUMERO_LONGO:
        return "***"
    if isinstance(valor, dict):
        return {chave: _limpar(item) for chave, item in valor.items()}
    if isinstance(valor, list | tuple):
        return [_limpar(item) for item in valor]
    return valor
