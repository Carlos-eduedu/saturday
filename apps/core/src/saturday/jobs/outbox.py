"""Consumo do outbox: o único dono do reagendamento.

O canal classifica (`Resultado`) e para. Aqui ficam a espera, o teto de
tentativas, a conversão para modelo quando a janela fechou do lado da Meta e a
espera pelo cliente depois do modelo.

Backoff exponencial com jitter: `base × 2^(n−1) × U(0,5; 1,5)`, teto de 300 s.
O jitter existe para dois workers não baterem na Meta no mesmo instante depois
de uma queda.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import Resultado
from saturday.dados import outbox as fila
from saturday.dados.modelos import Integracao, Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.services.webhook import WebhookClient, cabecalhos_assinados, corpo_json
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Teto do backoff: um envio preso não pode esperar horas para ser tentado.
ESPERA_MAXIMA_S = 300.0
# Fração do jitter em torno da espera calculada.
JITTER = 0.5
# Timeout de leitura pode ter chegado: uma nova tentativa, nunca duas.
MAX_TENTATIVAS_INCERTO = 2


class Entregador(Protocol):
    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado: ...


class EntregadorWebhook:
    """Entrega pelo webhook configurado.

    O webhook não distingue temporário de permanente: qualquer falha vale nova
    tentativa, como antes da mudança de política do canal WhatsApp.
    """

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._webhook = WebhookClient(http, settings)

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        if self._webhook.enviar(linha.payload):
            return Resultado.OK
        return Resultado.TEMPORARIO


# O aviso divide o laço do worker com o WhatsApp: um endpoint parado não pode
# segurar o lote. Timeout curto e, depois de uma falha, a integração espera.
TIMEOUT_INTEGRACAO_S = 3.0
PAUSA_INTEGRACAO_S = 60.0


class FalhaDoAviso(Exception):
    """Motivo curto da falha, que vai para `ultimo_erro` e a tela de entregas.

    Nunca a mensagem da exceção de rede: ela pode trazer a URL da integração.
    """


class EntregadorIntegracao:
    """Aviso de status ao webhook de uma integração (decisão 0035).

    URL e segredo são lidos na entrega: troca de endereço vale para o que está
    na fila. Integração revogada, apagada ou sem webhook desiste. Qualquer outra
    falha vale nova tentativa, como no webhook do `/chat`, e põe a integração
    em pausa: as outras linhas dela nem chamam até a pausa passar.
    """

    def __init__(
        self,
        http: httpx.Client,
        fabrica: sessionmaker[Session],
        *,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._fabrica = fabrica
        self._relogio = relogio
        self._pausada_ate: dict[Any, float] = {}

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        if self._relogio() < self._pausada_ate.get(linha.integracao_id, 0.0):
            raise FalhaDoAviso("em pausa depois de uma falha recente")
        with abrir_sessao(self._fabrica) as sessao:
            integracao = sessao.get(Integracao, linha.integracao_id)
            if integracao is None or integracao.revogada_em is not None:
                return Resultado.PERMANENTE
            url, segredo = integracao.webhook_url, integracao.webhook_segredo
        if not url or not segredo:
            return Resultado.PERMANENTE
        corpo = corpo_json(linha.payload)
        inicio = time.monotonic()
        situacao: int | None = None
        motivo = ""
        try:
            resposta = self._http.post(
                url,
                content=corpo,
                # O id da linha deixa o APP MEX descartar o aviso repetido.
                headers={
                    **cabecalhos_assinados(segredo, corpo),
                    "X-Saturday-Entrega": str(linha.id),
                },
                timeout=TIMEOUT_INTEGRACAO_S,
            )
            situacao = resposta.status_code
        except Exception as exc:  # noqa: BLE001 - só o tipo: a mensagem pode trazer a URL
            motivo = f"sem resposta ({type(exc).__name__})"
            logger.warning(
                "integracao_webhook_falhou integracao=%s erro=%s",
                linha.integracao_id,
                type(exc).__name__,
            )
        finally:
            # Só metadados: o corpo leva dados do cliente (regra 9).
            logger.info(
                "integracao_webhook integracao=%s entrega=%s status=%s ms=%d",
                linha.integracao_id,
                linha.id,
                situacao,
                (time.monotonic() - inicio) * 1000,
            )
        if situacao is not None and 200 <= situacao < 300:
            self._pausada_ate.pop(linha.integracao_id, None)
            return Resultado.OK
        self._pausada_ate[linha.integracao_id] = self._relogio() + PAUSA_INTEGRACAO_S
        raise FalhaDoAviso(motivo or f"respondeu {situacao}")


class EntregadorPorCanal:
    """Despacha pelo `canal` da linha do outbox."""

    def __init__(self, entregadores: dict[str, Entregador]) -> None:
        self._entregadores = entregadores

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        entregador = self._entregadores.get(linha.canal)
        if entregador is None:
            raise ValueError(f"canal sem entregador: {linha.canal}")
        return entregador.entregar(linha, permitir_modelo=permitir_modelo)


def _espera(tentativas: int, base: float) -> float:
    exponencial = base * (2 ** max(tentativas - 1, 0))
    sorteio = float(random.uniform(1 - JITTER, 1 + JITTER))  # noqa: S311 - jitter
    espera = exponencial * sorteio
    return espera if espera < ESPERA_MAXIMA_S else ESPERA_MAXIMA_S


def _entregar(entregador: Entregador, linha: Outbox) -> tuple[Resultado, str]:
    """Tenta entregar; na janela fechada, converte para modelo uma vez."""

    try:
        resultado = entregador.entregar(linha)
    except Exception as exc:  # noqa: BLE001 - o erro vai para a linha, não derruba o lote
        return Resultado.TEMPORARIO, f"{type(exc).__name__}: {exc}"

    if resultado is not Resultado.JANELA_FECHADA:
        return resultado, ""

    logger.info("outbox_converte_para_modelo id=%s", linha.id)
    try:
        return entregador.entregar(linha, permitir_modelo=True), ""
    except Exception as exc:  # noqa: BLE001
        return Resultado.TEMPORARIO, f"modelo: {type(exc).__name__}: {exc}"


def _aplicar(
    sessao: Session,
    linha: Outbox,
    resultado: Resultado,
    erro: str,
    settings: Settings,
) -> None:
    if resultado is Resultado.OK:
        fila.marcar_entregue(sessao, linha)
        logger.info("outbox_entregue id=%s canal=%s", linha.id, linha.canal)
        return

    if resultado is Resultado.AGUARDANDO_CLIENTE:
        fila.marcar_aguardando_cliente(sessao, linha)
        logger.info("outbox_aguardando_cliente id=%s canal=%s", linha.id, linha.canal)
        return

    if resultado is Resultado.PERMANENTE:
        fila.marcar_desistencia(sessao, linha, erro=f"permanente: {erro}")
        logger.error(
            "outbox_desistiu id=%s canal=%s motivo=permanente erro=%s",
            linha.id,
            linha.canal,
            erro,
        )
        return

    limite = (
        MAX_TENTATIVAS_INCERTO
        if resultado is Resultado.TEMPORARIO_INCERTO
        else settings.outbox_max_tentativas
    )

    if linha.tentativas >= limite:
        fila.marcar_desistencia(sessao, linha, erro=f"{resultado}: {erro}")
        logger.error(
            "outbox_desistiu id=%s canal=%s motivo=%s tentativas=%s erro=%s",
            linha.id,
            linha.canal,
            resultado,
            linha.tentativas,
            erro,
        )
        return

    espera = _espera(linha.tentativas, settings.outbox_backoff_base_s)
    fila.marcar_falha(sessao, linha, erro=f"{resultado}: {erro}", espera_s=espera)
    logger.warning(
        "outbox_falhou id=%s canal=%s resultado=%s tentativas=%s espera_s=%.1f erro=%s",
        linha.id,
        linha.canal,
        resultado,
        linha.tentativas,
        espera,
        erro,
    )


def drenar(
    fabrica: sessionmaker[Session],
    entregador: Entregador,
    settings: Settings,
) -> int:
    """Reivindica um lote, entrega e grava o resultado. Devolve quantos tentou.

    A entrega acontece **fora** da transação: segurar a linha travada durante
    uma chamada de rede seria pior do que o problema que a trava resolve.
    """

    with abrir_sessao(fabrica) as reserva:
        linhas = fila.reivindicar(reserva, settings.outbox_lote)

    if not linhas:
        return 0

    for linha in linhas:
        resultado, erro = _entregar(entregador, linha)
        with abrir_sessao(fabrica) as sessao:
            atual = sessao.get(Outbox, linha.id)
            if atual is None:
                continue
            _aplicar(sessao, atual, resultado, erro, settings)

    return len(linhas)
