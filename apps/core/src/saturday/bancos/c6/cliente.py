"""Cliente HTTP da API do C6 Consignado (contrato novo e refinanciamento INSS).

Rotas, cabeçalhos e campos saem do "Manual API V31.5" do banco (docs/c6.md):

- token por usuário e senha, em cache por processo, renovado 1 min antes de
  vencer; vai no `Authorization` sem "Bearer"; em 401, renova e repete uma vez;
- GET repete uma vez em erro de rede ou 5xx; POST nunca repete (só depois de
  um 401, quando o banco nem olhou o pedido);
- inclusão sem resposta conclusiva vira `ErroIncerto`. A API não tem busca de
  proposta por CPF: quem chama não repete, abre alerta para um atendente.

Cada chamada deixa em ``chamadas_externas`` só a rota, sem a query string.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import ChamadaExterna
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import registrar_chamada
from saturday.settings import Settings

logger = logging.getLogger(__name__)

PARCEIRO = "c6"
TIMEOUT_S = 30
ESPERA_RETRY_S = 1.5
RENOVAR_ANTES_S = 60

# O manual traz dois `Accept` para a simulação: este, na tabela de cabeçalhos e
# no exemplo de INSS, e `application/vnd.c6bank_simulation_v1+json` no de SIAPE.
# TODO(c6): qual dos dois vale para INSS? A resposta muda de formato?
ACCEPT_PROPOSTA = "application/vnd.c6bank_error_data_v2+json"
ACCEPT_CONSULTA = "application/vnd.c6bank_fgts_consult_v2+json"
ACCEPT_LINK = "application/vnd.c6bank_url_consult_v1+json"

ROTA_LOGIN = "/auth/token"
ROTA_SIMULACAO = "/marketplace/proposal/simulation"
ROTA_PROPOSTA = "/marketplace/proposal"
ROTA_LINK = "/marketplace/proposal/formalization-url"

# "Tipo de Produto" do manual: margem livre e refinanciamento.
PRODUTO = {"NOVA": "0001", "REFINANCIAMENTO": "0002"}
ORGAO_PADRAO = "000001"


class ErroC6(Exception):
    """Resposta de erro comprovada (o banco recusou ou não foi alcançado)."""

    def __init__(self, mensagem: str, *, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


class ErroIncerto(ErroC6):
    """POST sem resposta conclusiva (timeout, 5xx): pode ter sido feito."""


@dataclass(frozen=True)
class PedidoSimulacao:
    operacao: Literal["NOVA", "REFINANCIAMENTO"]
    cpf: str
    beneficio: str  # `client.enrollment`: o número do benefício
    nascimento: date
    renda: Decimal
    parcelas: int
    # Um dos dois: o que vier decide o `simulation_type`.
    valor_solicitado: Decimal | None = None
    valor_parcela: Decimal | None = None
    contratos: tuple[str, ...] = ()  # só no refinanciamento


@dataclass(frozen=True)
class Simulacao:
    convenio: str
    produto: str
    parcelas: int
    valor_solicitado: Decimal
    principal: Decimal
    parcela: Decimal
    iof: Decimal
    valor_cliente: Decimal
    taxa_mensal: Decimal
    bruto: dict[str, Any]  # a inclusão devolve ao banco os valores da simulação


@dataclass(frozen=True)
class LinkFormalizacao:
    url: str
    ativo: bool


def _decimal(dados: dict[str, Any], chave: str) -> Decimal:
    valor = dados.get(chave)
    if isinstance(valor, bool) or not isinstance(valor, int | float | str):
        raise ErroC6(f"simulação sem {chave}")
    return Decimal(str(valor))


def _codigo(dados: dict[str, Any], chave: str) -> str:
    bloco = dados.get(chave)
    codigo = bloco.get("code") if isinstance(bloco, dict) else None
    if not isinstance(codigo, str) or not codigo:
        raise ErroC6(f"simulação sem {chave}.code")
    return codigo


def corpo_da_simulacao(pedido: PedidoSimulacao, promotora: str) -> dict[str, Any]:
    if (pedido.valor_solicitado is None) == (pedido.valor_parcela is None):
        raise ValueError("informe o valor solicitado ou o valor da parcela, um só")
    if (pedido.operacao == "REFINANCIAMENTO") != bool(pedido.contratos):
        raise ValueError("refinanciamento exige contratos; contrato novo não leva")
    corpo: dict[str, Any] = {
        "operation_type": pedido.operacao,
        "product_type_code": PRODUTO[pedido.operacao],
        "formalization_subtype": "DIGITAL_WEB",
        "promoter_code": promotora,
        "covenant_group": "INSS",
        "public_agency": ORGAO_PADRAO,
        "installment_quantity": pedido.parcelas,
        "client": {
            "tax_identifier": pedido.cpf,
            "enrollment": pedido.beneficio,
            "birth_date": pedido.nascimento.isoformat(),
            "income_amount": float(pedido.renda),
        },
    }
    if pedido.valor_parcela is not None:
        corpo["simulation_type"] = "POR_VALOR_PARCELA"
        corpo["installment_amount"] = float(pedido.valor_parcela)
    else:
        corpo["simulation_type"] = "POR_VALOR_SOLICITADO"
        corpo["requested_amount"] = float(pedido.valor_solicitado or 0)
    if pedido.contratos:
        corpo["refinancing_contracts"] = list(pedido.contratos)
    return corpo


class ClienteC6:
    def __init__(
        self,
        http: httpx.Client,
        settings: Settings,
        fabrica: sessionmaker[Session],
        *,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._settings = settings
        self._fabrica = fabrica
        self._base = settings.c6_base_url.rstrip("/")
        self._relogio = relogio
        self._dormir = dormir
        self._trava_token = threading.Lock()
        self._token: str | None = None
        self._vence_em = 0.0

    # ------------------------------------------------------------------ token

    def _token_valido(self, *, renovar: bool = False) -> str:
        with self._trava_token:
            agora = self._relogio()
            if renovar or self._token is None or agora >= self._vence_em - RENOVAR_ANTES_S:
                dados = self._enviar(
                    "POST",
                    ROTA_LOGIN,
                    data={
                        "username": self._settings.c6_usuario,
                        "password": self._settings.c6_senha.get_secret_value(),
                    },
                )
                token = dados.get("access_token") if isinstance(dados, dict) else None
                if not isinstance(token, str) or not token:
                    raise ErroC6("login sem token")
                dura = dados.get("expires_in_seconds")
                self._token = token
                self._vence_em = agora + (float(dura) if isinstance(dura, int | float) else 0.0)
            return self._token

    # ------------------------------------------------------------------ HTTP

    def _enviar(
        self,
        metodo: str,
        rota: str,
        *,
        accept: str | None = None,
        token: str | None = None,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        conversa_id: Any = None,
    ) -> Any:
        """Uma requisição, sem retry. Classifica a falha e registra os metadados."""

        cabecalhos = {}
        if accept:
            cabecalhos["Accept"] = accept
        if token:
            cabecalhos["Authorization"] = token  # sem "Bearer", como pede o manual
        inicio = time.monotonic()
        situacao: int | None = None
        try:
            resposta = self._http.request(
                metodo,
                f"{self._base}{rota}",
                params=params,
                json=json,
                data=data,
                headers=cabecalhos,
                timeout=TIMEOUT_S,
            )
            situacao = resposta.status_code
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Não chegou a sair: seguro até para POST.
            raise ErroC6(f"rede: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            if metodo == "GET":
                raise ErroC6(f"rede: {type(exc).__name__}") from exc
            raise ErroIncerto(f"sem resposta: {type(exc).__name__}") from exc
        finally:
            self._registrar(metodo, rota, situacao, inicio, conversa_id)

        if situacao >= 500 and metodo != "GET":
            raise ErroIncerto(f"{metodo} {rota}: {situacao}", status=situacao)
        if situacao >= 400:
            raise ErroC6(f"{metodo} {rota}: {situacao}", status=situacao)
        try:
            return resposta.json()
        except ValueError as exc:
            # Num POST, 2xx sem corpo legível não diz o que o banco fez.
            tipo = ErroC6 if metodo == "GET" else ErroIncerto
            raise tipo(f"{metodo} {rota}: resposta não é JSON") from exc

    def _chamar(self, metodo: str, rota: str, *, accept: str, **extras: Any) -> Any:
        renovou = False
        repetiu = False
        while True:
            token = self._token_valido()
            try:
                return self._enviar(metodo, rota, accept=accept, token=token, **extras)
            except ErroIncerto:
                raise
            except ErroC6 as erro:
                if erro.status == 401 and not renovou:
                    renovou = True
                    self._token_valido(renovar=True)
                    continue
                transitorio = erro.status is None or erro.status >= 500
                if metodo == "GET" and transitorio and not repetiu:
                    repetiu = True
                    self._dormir(ESPERA_RETRY_S)
                    continue
                raise

    def _registrar(
        self, metodo: str, rota: str, situacao: int | None, inicio: float, conversa_id: Any
    ) -> None:
        duracao_ms = (time.monotonic() - inicio) * 1000
        registrar_chamada(PARCEIRO, duracao_ms, status=situacao if situacao else "erro")
        logger.info(
            "c6_chamada metodo=%s rota=%s status=%s ms=%.0f", metodo, rota, situacao, duracao_ms
        )
        try:
            with abrir_sessao(self._fabrica) as sessao:
                sessao.add(
                    ChamadaExterna(
                        conversa_id=conversa_id,
                        servico=PARCEIRO,
                        metodo=metodo,
                        rota=rota,
                        status_http=situacao,
                        duracao_ms=int(duracao_ms),
                    )
                )
        except Exception:  # noqa: BLE001 - o registro não pode derrubar a chamada
            logger.exception("c6_registro_falhou rota=%s", rota)

    # ------------------------------------------------------------------ operações

    def simular(self, pedido: PedidoSimulacao, *, conversa_id: Any = None) -> Simulacao:
        dados = self._chamar(
            "POST",
            ROTA_SIMULACAO,
            accept=ACCEPT_PROPOSTA,
            json=corpo_da_simulacao(pedido, self._settings.c6_codigo_promotora),
            conversa_id=conversa_id,
        )
        if not isinstance(dados, dict):
            raise ErroC6("simulação em formato inesperado")
        parcelas = dados.get("installment_quantity")
        if isinstance(parcelas, bool) or not isinstance(parcelas, int):
            raise ErroC6("simulação sem installment_quantity")
        return Simulacao(
            convenio=_codigo(dados, "covenant"),
            produto=_codigo(dados, "product"),
            parcelas=parcelas,
            valor_solicitado=_decimal(dados, "requested_amount"),
            principal=_decimal(dados, "principal_amount"),
            parcela=_decimal(dados, "installment_amount"),
            iof=_decimal(dados, "iof_amount"),
            valor_cliente=_decimal(dados, "client_amount"),
            taxa_mensal=_decimal(dados, "monthly_customer_rate"),
            bruto=dados,
        )

    def incluir(self, corpo: dict[str, Any], *, conversa_id: Any = None) -> str:
        """Inclui a proposta e devolve o número. Sem retry (regra 4).

        Quem chama grava a intenção antes e, em `ErroIncerto`, não repete.
        """

        dados = self._chamar(
            "POST", ROTA_PROPOSTA, accept=ACCEPT_PROPOSTA, json=corpo, conversa_id=conversa_id
        )
        numero = dados.get("proposal_number") if isinstance(dados, dict) else None
        if not isinstance(numero, str) or not numero:
            # O banco respondeu 2xx: a proposta pode existir sem o número ter chegado.
            raise ErroIncerto("inclusão sem proposal_number")
        return numero

    def consultar(self, numero: str, *, conversa_id: Any = None) -> dict[str, Any]:
        dados = self._chamar(
            "GET",
            ROTA_PROPOSTA,
            accept=ACCEPT_CONSULTA,
            params={"proposalNumber": numero},
            conversa_id=conversa_id,
        )
        if not isinstance(dados, dict):
            raise ErroC6("consulta em formato inesperado")
        return dados

    def link_formalizacao(self, numero: str, *, conversa_id: Any = None) -> LinkFormalizacao:
        dados = self._chamar(
            "GET",
            ROTA_LINK,
            accept=ACCEPT_LINK,
            params={"proposalNumber": numero},
            conversa_id=conversa_id,
        )
        url = dados.get("url") if isinstance(dados, dict) else None
        if not isinstance(url, str) or not url:
            raise ErroC6("link de formalização sem url")
        return LinkFormalizacao(url=url, ativo=dados.get("status") == "ACTIVE")
