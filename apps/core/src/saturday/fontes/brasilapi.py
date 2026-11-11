"""BrasilAPI: dados públicos de empresa por CNPJ, com cache de 30 dias.

Só empresa: a busca por CPF (NovaVida) fica para quando entrar
(docs/decisoes/0006). O cache guarda só os campos da regra da empresa; o quadro
de sócios, que traz nomes de pessoas, nunca é gravado.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import ChamadaExterna, EmpresaCnpj
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import registrar_chamada

logger = logging.getLogger(__name__)

SERVICO = "brasilapi"
BASE_URL = "https://brasilapi.com.br"
ROTA = "/api/cnpj/v1/{cnpj}"
CACHE = timedelta(days=30)
TIMEOUT_S = 10
ESPERA_RETRY_S = 1.5
CAMPOS = (
    "cnpj",
    "razao_social",
    "descricao_situacao_cadastral",
    "data_inicio_atividade",
    "opcao_pelo_mei",
    "codigo_porte",
)


class ErroBrasilAPI(Exception):
    """A BrasilAPI não respondeu depois da repetição."""


class BrasilAPI:
    def __init__(
        self,
        http: httpx.Client,
        fabrica: sessionmaker[Session] | None,
        *,
        base_url: str = BASE_URL,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._fabrica = fabrica
        self._base = base_url.rstrip("/")
        self._dormir = dormir

    def buscar_empresa(self, cnpj: str, *, conversa_id: Any = None) -> dict[str, Any] | None:
        """Dados da empresa, ou ``None`` se o CNPJ não existe.

        Erro de rede ou 5xx repete uma vez; persistindo, levanta ``ErroBrasilAPI``.
        """

        em_cache = self._do_cache(cnpj)
        if em_cache is not None:
            return em_cache
        for tentativa in (1, 2):
            situacao = self._chamar(cnpj, conversa_id)
            if isinstance(situacao, dict):
                self._guardar(cnpj, situacao)
                return situacao
            if situacao == 404:
                return None
            if tentativa == 1:
                self._dormir(ESPERA_RETRY_S)
        raise ErroBrasilAPI(f"cnpj indisponível: {situacao}")

    def _chamar(self, cnpj: str, conversa_id: Any) -> dict[str, Any] | int | None:
        """Os dados recortados, ou o status HTTP da falha (``None`` sem resposta)."""

        inicio = time.monotonic()
        situacao: int | None = None
        try:
            resposta = self._http.get(f"{self._base}/api/cnpj/v1/{cnpj}", timeout=TIMEOUT_S)
            situacao = resposta.status_code
        except httpx.HTTPError:
            return None
        finally:
            self._registrar(situacao, inicio, conversa_id)
        if situacao != 200:
            return situacao
        try:
            dados = resposta.json()
        except ValueError:
            return 502
        if not isinstance(dados, dict):
            return 502
        return {campo: dados.get(campo) for campo in CAMPOS}

    def _do_cache(self, cnpj: str) -> dict[str, Any] | None:
        if self._fabrica is None:
            return None
        with abrir_sessao(self._fabrica) as sessao:
            linha = sessao.get(EmpresaCnpj, cnpj)
            if linha is None or linha.buscada_em < datetime.now(UTC) - CACHE:
                return None
            return dict(linha.dados)

    def _guardar(self, cnpj: str, dados: dict[str, Any]) -> None:
        if self._fabrica is None:
            return
        with abrir_sessao(self._fabrica) as sessao:
            sessao.execute(
                insert(EmpresaCnpj)
                .values(cnpj=cnpj, dados=dados)
                .on_conflict_do_update(
                    index_elements=["cnpj"],
                    set_={"dados": dados, "buscada_em": datetime.now(UTC)},
                )
            )

    def _registrar(self, situacao: int | None, inicio: float, conversa_id: Any) -> None:
        duracao_ms = (time.monotonic() - inicio) * 1000
        registrar_chamada(SERVICO, duracao_ms)
        logger.info("brasilapi_chamada rota=%s status=%s ms=%.0f", ROTA, situacao, duracao_ms)
        if self._fabrica is None:
            return
        try:
            with abrir_sessao(self._fabrica) as sessao:
                sessao.add(
                    ChamadaExterna(
                        conversa_id=conversa_id,
                        servico=SERVICO,
                        metodo="GET",
                        rota=ROTA,
                        status_http=situacao,
                        duracao_ms=int(duracao_ms),
                    )
                )
        except Exception:  # noqa: BLE001 - o registro não pode derrubar a chamada
            logger.exception("brasilapi_registro_falhou")
