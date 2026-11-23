"""Histórico do token: grava cada chamada autenticada de uma integração ao proxy.

Quem autentica é a dependência `integracao`, que deixa o id em
`request.state`; aqui só se mede o tempo, pega o status e grava depois da
resposta. Chamada sem token válido não tem dono e não entra.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import integracoes

logger = logging.getLogger(__name__)

PREFIXO = "/integracao/"
# O formato do `Id` das rotas. A validação do caminho roda depois do token:
# num 422 o valor cru (talvez um CPF) chega aqui e não pode ser gravado.
ID_ACEITO = re.compile(r"[A-Za-z0-9_-]{1,64}")


class RegistroDeChamadas:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith(PREFIXO):
            await self.app(scope, receive, send)
            return

        status = 500
        inicio = time.monotonic()

        async def enviar(mensagem: dict[str, Any]) -> None:
            nonlocal status
            if mensagem["type"] == "http.response.start":
                status = int(mensagem["status"])
            await send(mensagem)

        try:
            await self.app(scope, receive, enviar)
        finally:
            integracao_id = (scope.get("state") or {}).get("integracao_id")
            if integracao_id is not None:
                rota = getattr(scope.get("route"), "path", None) or str(scope["path"])
                ids = {
                    k: str(v) if ID_ACEITO.fullmatch(str(v)) else "?"
                    for k, v in (scope.get("path_params") or {}).items()
                }
                duracao_ms = round((time.monotonic() - inicio) * 1000)
                fabrica: sessionmaker[Session] = scope["app"].state.fabrica
                try:
                    await run_in_threadpool(
                        _gravar,
                        fabrica,
                        integracao_id,
                        scope["method"],
                        rota,
                        ids,
                        status,
                        duracao_ms,
                    )
                except Exception:
                    # Falhar o registro não derruba a resposta, que já saiu.
                    logger.exception("integracao_chamada_nao_gravada")


def _gravar(
    fabrica: sessionmaker[Session],
    integracao_id: Any,
    metodo: str,
    rota: str,
    ids: dict[str, str],
    status: int,
    duracao_ms: int,
) -> None:
    with abrir_sessao(fabrica) as sessao:
        integracoes.gravar_chamada_do_token(
            sessao, integracao_id, metodo, rota, ids, status, duracao_ms
        )
