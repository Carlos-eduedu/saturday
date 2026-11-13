"""Cliente HTTP da API de parceiros da Granatech.

Regras do contrato (AGENTS.md, "Especificação: API Granatech"):

- token em cache por processo, renovado 5 min antes de vencer; em 401, renova
  e repete uma vez;
- GET repete uma vez em erro de rede ou 5xx; POST nunca repete (só depois de
  um 401, quando a Granatech nem olhou o pedido);
- nenhuma consulta sem passar pelo reaproveitamento e pela cota;
- proposta gravada como intenção antes do POST; em resultado incerto, procurar
  na listagem antes de qualquer nova tentativa.

Cada chamada deixa em ``chamadas_externas`` só a rota-modelo: a consulta leva
CPF, nome e telefone na query string.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech import status as ordem
from saturday.bancos.granatech.normalizacao import (
    DetalheConsulta,
    Simulacao,
    id_da_proposta,
    itens_da_listagem,
    normalizar_detalhe,
    normalizar_simulacao,
    recortar_detalhe,
)
from saturday.bancos.granatech.numeros import decimal_ou_none
from saturday.bancos.granatech.teto import MAX_NOVAS_SIMULACOES, proxima_parcela
from saturday.dados import cota
from saturday.dados.modelos import ChamadaExterna, ConsultaGranatech, PropostaGranatech
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import registrar_chamada
from saturday.settings import (
    GRANATECH_ESPERA_RETRY_S,
    GRANATECH_TIMEOUT_S,
    TZ_OPERACAO,
    Settings,
)

logger = logging.getLogger(__name__)

PARCEIRO = "granatech"
CACHE_BANCOS_S = 24 * 3600
CONSIGNADO = "/api-consignado/v1"
RENOVAR_ANTES_S = 300
TOKEN_PADRAO_S = 3600
# Proposta da listagem criada um pouco antes da intenção ainda casa: os
# relógios da Granatech e do nosso banco não são o mesmo.
FOLGA_RELOGIO = timedelta(minutes=5)

_DURACAO = re.compile(r"^\s*(\d+)\s*(h|m|min|s)?\s*$", re.IGNORECASE)


class ErroGranatech(Exception):
    """Resposta de erro comprovada (a Granatech recusou ou não foi alcançada)."""

    def __init__(self, mensagem: str, *, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


class ErroIncerto(ErroGranatech):
    """POST sem resposta conclusiva (timeout, 5xx): pode ter sido feito."""


@dataclass(frozen=True)
class ConsultaAberta:
    id_local: int
    id_externo: str
    status: str
    link_termo: str | None
    reaproveitada: bool


def expira_em_segundos(valor: object, agora: datetime) -> float:
    """``expira_em`` do login: "1h", segundos, minutos ou data ISO; na dúvida, 1 h."""

    if isinstance(valor, int | float) and not isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, str):
        casou = _DURACAO.match(valor)
        if casou:
            numero = float(casou.group(1))
            unidade = (casou.group(2) or "s").lower()
            return numero * {"h": 3600, "m": 60, "min": 60, "s": 1}[unidade]
        try:
            fim = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return TOKEN_PADRAO_S
        if fim.tzinfo is None:
            fim = fim.replace(tzinfo=UTC)
        return max((fim - agora).total_seconds(), 0.0)
    return TOKEN_PADRAO_S


def _data_hora(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        lida = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return lida if lida.tzinfo else lida.replace(tzinfo=ZoneInfo(TZ_OPERACAO))


def _criada_em(item: dict[str, Any]) -> datetime | None:
    for chave in ("created_at", "criado_em", "criada_em", "data_criacao"):
        lida = _data_hora(item.get(chave))
        if lida is not None:
            return lida
    return None


class ClienteGranatech:
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
        self._base = settings.granatech_base_url.rstrip("/")
        self._relogio = relogio
        self._dormir = dormir
        self._trava_token = threading.Lock()
        self._token: str | None = None
        self._vence_em = 0.0
        self._bancos: list[dict[str, Any]] | None = None
        self._bancos_ate = 0.0

    # ------------------------------------------------------------------ token

    def _token_valido(self, *, renovar: bool = False) -> str:
        with self._trava_token:
            agora = self._relogio()
            if renovar or self._token is None or agora >= self._vence_em - RENOVAR_ANTES_S:
                self._login(agora)
            if self._token is None:
                raise ErroGranatech("login sem token")
            return self._token

    def _login(self, agora: float) -> None:
        dados = self._enviar(
            "POST",
            "/api/v1/auth/login",
            "/api/v1/auth/login",
            json={"chave_api": self._settings.granatech_chave_api.get_secret_value()},
            token=None,
        )
        token = dados.get("token") if isinstance(dados, dict) else None
        if not isinstance(token, str) or not token:
            raise ErroGranatech("login sem token")
        self._token = token
        self._vence_em = agora + expira_em_segundos(dados.get("expira_em"), datetime.now(UTC))

    # ------------------------------------------------------------------ HTTP

    def _enviar(
        self,
        metodo: str,
        rota_modelo: str,
        caminho: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        token: str | None,
        conversa_id: Any = None,
    ) -> Any:
        """Uma requisição, sem retry. Classifica a falha e registra os metadados."""

        cabecalhos = {"Authorization": f"Bearer {token}"} if token else {}
        inicio = time.monotonic()
        situacao: int | None = None
        try:
            resposta = self._http.request(
                metodo,
                f"{self._base}{caminho}",
                params=params,
                json=json,
                headers=cabecalhos,
                timeout=GRANATECH_TIMEOUT_S,
            )
            situacao = resposta.status_code
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Não chegou a sair: seguro até para POST.
            raise ErroGranatech(f"rede: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            if metodo == "GET":
                raise ErroGranatech(f"rede: {type(exc).__name__}") from exc
            raise ErroIncerto(f"sem resposta: {type(exc).__name__}") from exc
        finally:
            self._registrar(metodo, rota_modelo, situacao, inicio, conversa_id)

        if situacao >= 500 and metodo != "GET":
            raise ErroIncerto(f"{metodo} {rota_modelo}: {situacao}", status=situacao)
        if situacao >= 400:
            raise ErroGranatech(f"{metodo} {rota_modelo}: {situacao}", status=situacao)
        if not resposta.content:
            return {}
        try:
            return resposta.json()
        except ValueError as exc:
            raise ErroGranatech(f"{metodo} {rota_modelo}: resposta não é JSON") from exc

    def _chamar(
        self,
        metodo: str,
        rota_modelo: str,
        caminho: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        conversa_id: Any = None,
    ) -> Any:
        renovou = False
        repetiu = False
        while True:
            token = self._token_valido()
            try:
                return self._enviar(
                    metodo,
                    rota_modelo,
                    caminho,
                    params=params,
                    json=json,
                    token=token,
                    conversa_id=conversa_id,
                )
            except ErroIncerto:
                raise
            except ErroGranatech as erro:
                if erro.status == 401 and not renovou:
                    renovou = True
                    self._token_valido(renovar=True)
                    continue
                transitorio = erro.status is None or erro.status >= 500
                if metodo == "GET" and transitorio and not repetiu:
                    repetiu = True
                    self._dormir(GRANATECH_ESPERA_RETRY_S)
                    continue
                raise

    def _registrar(
        self,
        metodo: str,
        rota_modelo: str,
        situacao: int | None,
        inicio: float,
        conversa_id: Any,
    ) -> None:
        duracao_ms = (time.monotonic() - inicio) * 1000
        registrar_chamada(PARCEIRO, duracao_ms, status=situacao if situacao else "erro")
        logger.info(
            "granatech_chamada metodo=%s rota=%s status=%s ms=%.0f",
            metodo,
            rota_modelo,
            situacao,
            duracao_ms,
        )
        try:
            with abrir_sessao(self._fabrica) as sessao:
                sessao.add(
                    ChamadaExterna(
                        conversa_id=conversa_id,
                        servico=PARCEIRO,
                        metodo=metodo,
                        rota=rota_modelo,
                        status_http=situacao,
                        duracao_ms=int(duracao_ms),
                    )
                )
        except Exception:  # noqa: BLE001 - o registro não pode derrubar a chamada
            logger.exception("granatech_registro_falhou rota=%s", rota_modelo)

    # ------------------------------------------------------------------ consulta

    def abrir_consulta(
        self, cpf: str, nome: str, telefone: str, *, conversa_id: Any = None
    ) -> ConsultaAberta:
        """Reaproveita uma consulta recente do CPF ou abre outra, gastando cota.

        Levanta ``CotaEsgotada`` sem chamar a Granatech quando não há cota.
        """

        reaproveitada = self._consulta_local(cpf) or self._consulta_remota(cpf, conversa_id)
        if reaproveitada is not None:
            return reaproveitada

        hoje = datetime.now(ZoneInfo(TZ_OPERACAO)).date()
        with abrir_sessao(self._fabrica) as sessao:
            cota.reservar(
                sessao,
                parceiro=PARCEIRO,
                hoje=hoje,
                teto_dia=self._settings.granatech_cota_diaria,
                teto_mes=self._settings.granatech_cota_mensal,
            )

        try:
            dados = self._chamar(
                "GET",
                f"{CONSIGNADO}/consulta-saldo",
                f"{CONSIGNADO}/consulta-saldo",
                params={"cpf": cpf, "nome": nome, "telefone": telefone},
                conversa_id=conversa_id,
            )
        except ErroGranatech as erro:
            if erro.status is not None and 400 <= erro.status < 500 and erro.status != 401:
                self._devolver_cota(hoje)
            raise

        id_externo = str(dados.get("id") or "")
        if not id_externo:
            raise ErroGranatech("consulta sem id")
        return self._gravar_consulta(
            id_externo=id_externo,
            cpf=cpf,
            status=ordem.normalizar_consulta(
                str(dados.get("status") or "AWAITING_CLIENT_AUTHORIZATION")
            ),
            link_termo=dados.get("link_termo_consentimento"),
            conversa_id=conversa_id,
            reaproveitada=False,
        )

    def _devolver_cota(self, dia: date) -> None:
        with abrir_sessao(self._fabrica) as sessao:
            cota.devolver(sessao, parceiro=PARCEIRO, dia=dia)

    def _limite_reaproveitamento(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self._settings.granatech_reaproveitar_dias)

    def _consulta_local(self, cpf: str) -> ConsultaAberta | None:
        with abrir_sessao(self._fabrica) as sessao:
            linha = sessao.scalars(
                select(ConsultaGranatech)
                .where(
                    ConsultaGranatech.cpf == cpf,
                    ConsultaGranatech.criada_em >= self._limite_reaproveitamento(),
                    ConsultaGranatech.status.not_in(ordem.CONSULTA_SEM_REAPROVEITAMENTO),
                )
                .order_by(ConsultaGranatech.criada_em.desc())
                .limit(1)
            ).first()
            if linha is None:
                return None
            return ConsultaAberta(
                id_local=linha.id,
                id_externo=linha.id_externo,
                status=linha.status,
                link_termo=linha.link_termo,
                reaproveitada=True,
            )

    def _consulta_remota(self, cpf: str, conversa_id: Any) -> ConsultaAberta | None:
        limite = self._limite_reaproveitamento()
        candidatas = []
        for item in self.listar_consultas_por_cpf(cpf):
            criada = _criada_em(item)
            situacao = ordem.normalizar_consulta(str(item.get("status") or ""))
            # Sem data não dá para saber se está na janela: não reaproveita.
            if criada is None or criada < limite or not item.get("id"):
                continue
            if situacao in ordem.CONSULTA_SEM_REAPROVEITAMENTO:
                continue
            candidatas.append((criada, item))
        if not candidatas:
            return None
        _, item = max(candidatas, key=lambda par: par[0])
        return self._gravar_consulta(
            id_externo=str(item["id"]),
            cpf=cpf,
            status=ordem.normalizar_consulta(
                str(item.get("status") or "AWAITING_CLIENT_AUTHORIZATION")
            ),
            link_termo=item.get("link_termo_consentimento"),
            conversa_id=conversa_id,
            reaproveitada=True,
        )

    def _gravar_consulta(
        self,
        *,
        id_externo: str,
        cpf: str,
        status: str,
        link_termo: object,
        conversa_id: Any,
        reaproveitada: bool,
    ) -> ConsultaAberta:
        with abrir_sessao(self._fabrica) as sessao:
            linha = sessao.scalars(
                select(ConsultaGranatech).where(ConsultaGranatech.id_externo == id_externo)
            ).first()
            if linha is None:
                linha = ConsultaGranatech(
                    id_externo=id_externo,
                    cpf=cpf,
                    status=status,
                    link_termo=str(link_termo) if link_termo else None,
                    conversa_id=conversa_id,
                    historico=[],
                )
                sessao.add(linha)
                sessao.flush()
            return ConsultaAberta(
                id_local=linha.id,
                id_externo=linha.id_externo,
                status=linha.status,
                link_termo=linha.link_termo,
                reaproveitada=reaproveitada,
            )

    def listar_consultas_por_cpf(self, cpf: str) -> list[dict[str, Any]]:
        # TODO(granatech): qual dos dois parâmetros vale, `filterBy` ou `filtrar_por`.
        dados = self._chamar(
            "GET",
            f"{CONSIGNADO}/consulta-saldo/usuario",
            f"{CONSIGNADO}/consulta-saldo/usuario",
            params={"pagina": 1, "filterBy": "cpf", "filtrar_por": "cpf", "valor_filtro": cpf},
        )
        return itens_da_listagem(dados)

    def assinar_termo(
        self,
        *,
        id_consulta: str,
        cpf: str,
        email: str,
        nome: str,
        telefone: str,
        conversa_id: Any = None,
    ) -> None:
        """Assina o termo; se falhar, o plano B é mandar o ``link_termo``."""

        self._chamar(
            "POST",
            f"{CONSIGNADO}/termo-consentimento",
            f"{CONSIGNADO}/termo-consentimento",
            json={
                "cpf": cpf,
                "email": email,
                "nome": nome,
                "telefone": telefone,
                "id_consulta": id_consulta,
            },
            conversa_id=conversa_id,
        )

    def detalhe(self, id_consulta: str) -> tuple[DetalheConsulta | None, dict[str, Any]]:
        """Detalhe normalizado (``None`` se não pronto) e o recorte para gravar."""

        dados = self._chamar(
            "GET",
            f"{CONSIGNADO}/consulta-saldo/{{id}}",
            f"{CONSIGNADO}/consulta-saldo/{id_consulta}",
        )
        if not isinstance(dados, dict):
            raise ErroGranatech("detalhe em formato inesperado")
        return normalizar_detalhe(dados), recortar_detalhe(dados)

    def situacao(self, id_consulta: str) -> tuple[str, str | None, DetalheConsulta | None]:
        """Status, link do termo e detalhe já gravados localmente para a consulta."""

        with abrir_sessao(self._fabrica) as sessao:
            linha = sessao.scalars(
                select(ConsultaGranatech).where(ConsultaGranatech.id_externo == id_consulta)
            ).one()
            detalhe = normalizar_detalhe(linha.detalhe) if linha.detalhe else None
            return linha.status, linha.link_termo, detalhe

    def gravar_detalhe(self, id_consulta: str) -> DetalheConsulta | None:
        """Busca o detalhe e grava o recorte; ``None`` se ainda vier sem margens."""

        detalhe, recorte = self.detalhe(id_consulta)
        if detalhe is None:
            return None
        with abrir_sessao(self._fabrica) as sessao:
            linha = sessao.scalars(
                select(ConsultaGranatech).where(ConsultaGranatech.id_externo == id_consulta)
            ).one()
            linha.detalhe = recorte
        return detalhe

    # ------------------------------------------------------------------ simulação

    def simular(
        self,
        *,
        id_produto: str,
        id_margem: str,
        numero_parcelas: int,
        idade: int,
        valor_parcela: Decimal,
        seguro: bool = True,
        id_empresa_seguro: str | None = None,
        id_produto_seguro: str | None = None,
    ) -> Simulacao:
        params: dict[str, Any] = {
            "id_margem": id_margem,
            "numero_parcelas": numero_parcelas,
            "idade": idade,
            "valor_parcela": str(valor_parcela),
            "seguro": "true" if seguro else "false",
        }
        if id_empresa_seguro:
            params["id_empresa_seguro"] = id_empresa_seguro
        if id_produto_seguro:
            params["id_produto_seguro"] = id_produto_seguro
        dados = self._chamar(
            "GET",
            f"{CONSIGNADO}/simulacao/{{id_produto}}",
            f"{CONSIGNADO}/simulacao/{id_produto}",
            params=params,
        )
        if not isinstance(dados, dict):
            raise ErroGranatech("simulação em formato inesperado")
        return normalizar_simulacao(dados)

    @property
    def teto(self) -> Decimal:
        return self._settings.granatech_teto_liberado

    @property
    def proposta_ativa(self) -> bool:
        return self._settings.granatech_proposta_ativa

    @property
    def dados_bancarios_ativo(self) -> bool:
        return self._settings.granatech_dados_bancarios_ativo

    @property
    def tipo_empregador(self) -> int:
        return self._settings.granatech_tipo_empregador

    def historico_proposta(self, id_proposta: str) -> list[dict[str, Any]]:
        """Eventos recebidos da proposta, do mais antigo ao mais novo."""

        with abrir_sessao(self._fabrica) as sessao:
            historico = sessao.scalars(
                select(PropostaGranatech.historico).where(
                    PropostaGranatech.id_externo == id_proposta
                )
            ).first()
            return list(historico or [])

    def simular_no_teto(self, **pedido: Any) -> Simulacao | None:
        """Simula e, se o liberado passar do teto, reduz a parcela.

        Até 4 novas simulações; ``None`` quando não sobra oferta (parcela abaixo
        de R$ 45 ou o teto não foi alcançado).
        """

        teto = self._settings.granatech_teto_liberado
        simulacao = self.simular(**pedido)
        tentativa = 0
        while simulacao.liberado > teto:
            tentativa += 1
            if tentativa > MAX_NOVAS_SIMULACOES:
                return None
            nova = proxima_parcela(simulacao.valor_parcela, simulacao.liberado, teto, tentativa)
            if nova is None:
                return None
            simulacao = self.simular(**{**pedido, "valor_parcela": nova})
        return replace(simulacao, limitado_ao_teto=tentativa > 0)

    def bancos(self) -> list[dict[str, Any]]:
        """Bancos habilitados para receber o crédito."""

        dados = self._chamar("GET", f"{CONSIGNADO}/bancos", f"{CONSIGNADO}/bancos")
        return [b for b in itens_da_listagem(dados) if b.get("habilitado")]

    def bancos_em_cache(self) -> list[dict[str, Any]]:
        """``bancos()`` com cache de 1 dia no processo: a lista quase não muda."""

        agora = self._relogio()
        if self._bancos is None or agora >= self._bancos_ate:
            self._bancos = self.bancos()
            self._bancos_ate = agora + CACHE_BANCOS_S
        return self._bancos

    def criar_proposta(
        self,
        *,
        consulta_id: int,
        corpo: dict[str, Any],
        conversa_id: Any = None,
    ) -> str:
        """Cria a proposta uma única vez e devolve o id da Granatech.

        Grava a intenção antes do POST. Se a consulta já tem proposta criada,
        devolve a mesma; se tem uma incerta, reconcilia antes de qualquer POST.
        Levanta ``ErroIncerto`` quando a reconciliação não acha a proposta:
        quem chama decide (handoff), nunca um novo POST automático.
        """

        if not self._settings.granatech_proposta_ativa:
            raise RuntimeError("criação de proposta desligada (SATURDAY_GRANATECH_PROPOSTA_ATIVA)")

        financeiro = (corpo.get("informacoesFinanceira") or [{}])[0]
        parcela = decimal_ou_none(financeiro.get("valor_parcela"))
        prazo = int(financeiro.get("numero_parcelas") or 0)
        if parcela is None or not prazo:
            raise ValueError("corpo sem valor_parcela ou numero_parcelas")

        with abrir_sessao(self._fabrica) as sessao:
            anterior = sessao.scalars(
                select(PropostaGranatech)
                .where(
                    PropostaGranatech.consulta_id == consulta_id,
                    PropostaGranatech.estado_envio.in_(("intencao", "criada", "incerta")),
                )
                .order_by(PropostaGranatech.id.desc())
                .with_for_update()
            ).first()
            if anterior is not None and anterior.estado_envio == "criada" and anterior.id_externo:
                return anterior.id_externo
            if anterior is not None:
                # Intenção sem desfecho (o processo caiu no meio) é tão incerta quanto
                # um timeout: procurar antes de mandar de novo.
                anterior.estado_envio = "incerta"
                proposta_id = anterior.id
                pendente = True
            else:
                nova = PropostaGranatech(
                    consulta_id=consulta_id,
                    conversa_id=conversa_id,
                    estado_envio="intencao",
                    valor_parcela=parcela,
                    numero_parcelas=prazo,
                    historico=[],
                )
                sessao.add(nova)
                sessao.flush()
                proposta_id = nova.id
                pendente = False

        if pendente:
            achada = self.reconciliar_proposta(proposta_id)
            if achada is None:
                raise ErroIncerto("proposta anterior incerta e não encontrada na listagem")
            return achada

        try:
            dados = self._chamar(
                "POST",
                f"{CONSIGNADO}/propostas",
                f"{CONSIGNADO}/propostas",
                json=corpo,
                conversa_id=conversa_id,
            )
        except ErroIncerto:
            self._marcar_proposta(proposta_id, estado="incerta")
            achada = self.reconciliar_proposta(proposta_id)
            if achada is None:
                raise
            return achada
        except ErroGranatech:
            self._marcar_proposta(proposta_id, estado="falhou")
            raise

        id_externo = id_da_proposta(dados)
        if id_externo is None:
            # Criou, mas não sabemos o id: a listagem é quem diz.
            self._marcar_proposta(proposta_id, estado="incerta")
            achada = self.reconciliar_proposta(proposta_id)
            if achada is None:
                raise ErroIncerto("proposta criada sem id na resposta")
            return achada
        self._marcar_proposta(proposta_id, estado="criada", id_externo=id_externo)
        return id_externo

    def _marcar_proposta(
        self, proposta_id: int, *, estado: str, id_externo: str | None = None
    ) -> None:
        with abrir_sessao(self._fabrica) as sessao:
            proposta = sessao.get(PropostaGranatech, proposta_id)
            if proposta is None:
                return
            proposta.estado_envio = estado
            if id_externo is not None:
                proposta.id_externo = id_externo

    def reconciliar_proposta(self, proposta_id: int) -> str | None:
        """Procura na listagem por CPF a proposta de um POST incerto.

        Casa pela consulta, parcela e prazo, criada depois da intenção (com
        folga de relógio) e ainda não ligada a outra proposta nossa.
        """

        with abrir_sessao(self._fabrica) as sessao:
            proposta = sessao.get(PropostaGranatech, proposta_id)
            if proposta is None:
                return None
            consulta = sessao.get(ConsultaGranatech, proposta.consulta_id)
            if consulta is None:
                return None
            cpf = consulta.cpf
            id_consulta = consulta.id_externo
            parcela = proposta.valor_parcela
            prazo = proposta.numero_parcelas
            desde = proposta.intencao_em - FOLGA_RELOGIO
            conhecidas = set(
                sessao.scalars(
                    select(PropostaGranatech.id_externo).where(
                        PropostaGranatech.id_externo.is_not(None),
                        PropostaGranatech.id != proposta_id,
                    )
                ).all()
            )

        dados = self._chamar(
            "GET",
            f"{CONSIGNADO}/propostas/lista",
            f"{CONSIGNADO}/propostas/lista",
            params={"pagina": 1, "tamanho_pagina": 50, "termo_busca": cpf},
        )
        for item in itens_da_listagem(dados):
            id_externo = id_da_proposta(item)
            if id_externo is None or id_externo in conhecidas:
                continue
            if str(item.get("id_consulta") or "") != id_consulta:
                continue
            if decimal_ou_none(item.get("valor_parcela")) != parcela:
                continue
            if int(item.get("numero_parcelas") or 0) != prazo:
                continue
            criada = _criada_em(item)
            if criada is not None and criada < desde:
                continue
            self._marcar_proposta(proposta_id, estado="criada", id_externo=id_externo)
            logger.info("granatech_proposta_reconciliada proposta=%s", proposta_id)
            return id_externo
        return None

    def id_local_da_consulta(self, id_consulta: str) -> int:
        with abrir_sessao(self._fabrica) as sessao:
            return sessao.scalars(
                select(ConsultaGranatech.id).where(ConsultaGranatech.id_externo == id_consulta)
            ).one()

    def enviar_dados_tomador(
        self, id_proposta: str, corpo: dict[str, Any], *, conversa_id: Any = None
    ) -> None:
        """``POST /propostas/{id}/dados-tomador``. Sem retry, como todo POST."""

        self._chamar(
            "POST",
            f"{CONSIGNADO}/propostas/{{id}}/dados-tomador",
            f"{CONSIGNADO}/propostas/{id_proposta}/dados-tomador",
            json=corpo,
            conversa_id=conversa_id,
        )

    def cancelar(self, id_proposta: str, *, conversa_id: Any = None) -> None:
        """Cancela a proposta. Nesta fase só um atendente decide cancelar."""

        self._chamar(
            "POST",
            f"{CONSIGNADO}/propostas/{{id}}/cancelar",
            f"{CONSIGNADO}/propostas/{id_proposta}/cancelar",
            conversa_id=conversa_id,
        )

    def corrigir_dados_bancarios(
        self, id_proposta: str, banco_detalhe: dict[str, Any], *, conversa_id: Any = None
    ) -> None:
        """Nova conta depois de uma falha de pagamento.

        TODO(granatech): corpo do ``PATCH /propostas/{id}/dados-bancarios``. Enviamos
        o mesmo ``banco_detalhe`` dos dados do tomador; fica atrás de
        ``SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO`` até a Granatech confirmar.
        """

        if not self._settings.granatech_dados_bancarios_ativo:
            raise RuntimeError(
                "correção de conta desligada (SATURDAY_GRANATECH_DADOS_BANCARIOS_ATIVO)"
            )
        self._chamar(
            "PATCH",
            f"{CONSIGNADO}/propostas/{{id}}/dados-bancarios",
            f"{CONSIGNADO}/propostas/{id_proposta}/dados-bancarios",
            json={"tipo_dados_bancarios": "dados_bancarios", "banco_detalhe": banco_detalhe},
            conversa_id=conversa_id,
        )

    def status_proposta(self, id_proposta: str) -> dict[str, Any]:
        dados = self._chamar(
            "GET",
            f"{CONSIGNADO}/propostas/{{id}}",
            f"{CONSIGNADO}/propostas/{id_proposta}",
        )
        return dados if isinstance(dados, dict) else {}
