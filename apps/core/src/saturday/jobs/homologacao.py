"""Rodadas da homologação Granatech, executadas pelo worker (decisão 0014).

Uma rodada leva até ~30 min (esperas por margens e webhooks), por isso roda numa
thread própria: o laço do worker segue entregando o outbox. Uma rodada por vez
(índice único em ``homologacoes_granatech``). Os webhooks são lidos direto de
``eventos_recebidos``, sem passar pela API.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.homologacao import ErroHomologacao, Homologacao, disponivel
from saturday.dados import repositorios
from saturday.dados.modelos import EventoRecebido, HomologacaoGranatech
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import mascarar_cpf
from saturday.settings import Settings

logger = logging.getLogger(__name__)

ORIGEM = "granatech"


def eventos_do_id(sessao: Session, id_externo: str) -> list[dict[str, Any]]:
    """Eventos da Granatech recebidos para uma consulta ou proposta; CPF mascarado."""

    linhas = sessao.scalars(
        select(EventoRecebido)
        .where(
            EventoRecebido.origem == ORIGEM,
            or_(
                EventoRecebido.payload["id_solicitacao"].astext == id_externo,
                EventoRecebido.payload["id_consulta"].astext == id_externo,
                EventoRecebido.payload["id_proposta"].astext == id_externo,
            ),
        )
        .order_by(EventoRecebido.id)
    ).all()
    return [
        {
            "recebido_em": linha.recebido_em.isoformat(),
            "processado_em": linha.processado_em.isoformat() if linha.processado_em else None,
            "payload": {
                **(linha.payload or {}),
                "cpf": mascarar_cpf(str((linha.payload or {}).get("cpf") or "")),
            },
        }
        for linha in linhas
    ]


def eh_da_homologacao(sessao: Session, id_externo: str) -> bool:
    """O id foi criado por uma rodada: o webhook dele não é de cliente."""

    return bool(
        id_externo
        and sessao.scalar(
            select(HomologacaoGranatech.id)
            .where(HomologacaoGranatech.ids_externos.contains([id_externo]))
            .limit(1)
        )
    )


class Rodadas:
    """Dono da thread da rodada em andamento, dentro do worker."""

    def __init__(
        self, fabrica: sessionmaker[Session], settings: Settings, parar: threading.Event
    ) -> None:
        self.fabrica = fabrica
        self.settings = settings
        self.parar = parar
        self.thread: threading.Thread | None = None
        # shortcut: assume um worker só (compose atual); com vários workers,
        # trocar por batimento na rodada antes de interromper a dos outros.
        with abrir_sessao(fabrica) as sessao:
            sessao.execute(
                update(HomologacaoGranatech)
                .where(HomologacaoGranatech.situacao == "em_andamento")
                .values(
                    situacao="interrompida",
                    terminado_em=datetime.now(UTC),
                    erro="o worker reiniciou no meio da rodada",
                )
            )

    def verificar(self) -> bool:
        """Inicia a rodada pendente, se houver e nenhuma estiver rodando."""

        if self.thread is not None and self.thread.is_alive():
            return False
        with abrir_sessao(self.fabrica) as sessao:
            rodada = sessao.scalars(
                select(HomologacaoGranatech)
                .where(HomologacaoGranatech.situacao == "pendente")
                .with_for_update(skip_locked=True)
                .limit(1)
            ).first()
            if rodada is None:
                return False
            if not disponivel(self.settings):
                rodada.situacao = "falhou"
                rodada.terminado_em = datetime.now(UTC)
                rodada.erro = "homologação indisponível neste ambiente"
                repositorios.notificar(sessao, "homologacao", rodada=rodada.id)
                return False
            rodada.situacao = "em_andamento"
            rodada.iniciado_em = datetime.now(UTC)
            repositorios.notificar(sessao, "homologacao", rodada=rodada.id)
            rodada_id, fase = rodada.id, rodada.fase
        self.thread = threading.Thread(
            target=self._executar, args=(rodada_id, fase), name="homologacao", daemon=True
        )
        self.thread.start()
        return True

    def _executar(self, rodada_id: int, fase: int) -> None:
        logger.info("homologacao_iniciada rodada=%s fase=%s", rodada_id, fase)

        def salvar(h: Homologacao) -> None:
            with abrir_sessao(self.fabrica) as sessao:
                rodada = sessao.get(HomologacaoGranatech, rodada_id)
                if rodada is None:
                    return
                rodada.passos = list(h.passos)
                rodada.itens = h.itens()
                rodada.ids_externos = list(h.ids_externos)
                repositorios.notificar(sessao, "homologacao", rodada=rodada_id)

        def ler(id_externo: str) -> list[dict[str, Any]]:
            with abrir_sessao(self.fabrica) as sessao:
                return eventos_do_id(sessao, id_externo)

        def dormir(segundos: float) -> None:
            if self.parar.wait(segundos):
                raise ErroHomologacao("o worker parou no meio da rodada")

        try:
            with httpx.Client(
                base_url=self.settings.granatech_base_url, timeout=httpx.Timeout(30.0)
            ) as http:
                homologacao = Homologacao(
                    granatech=http,
                    chave=self.settings.granatech_chave_api.get_secret_value(),
                    ler_eventos=ler,
                    ao_mudar=salvar,
                    dormir=dormir,
                )
                erro = homologacao.rodar(fase)
        except Exception as exc:
            logger.exception("homologacao_erro rodada=%s", rodada_id)
            erro = f"erro interno: {type(exc).__name__}"

        with abrir_sessao(self.fabrica) as sessao:
            rodada = sessao.get(HomologacaoGranatech, rodada_id)
            if rodada is None:
                return
            if self.parar.is_set():
                rodada.situacao = "interrompida"
            else:
                falhou = erro is not None or not all(i["ok"] for i in rodada.itens)
                rodada.situacao = "falhou" if falhou else "concluida"
            rodada.erro = erro
            rodada.terminado_em = datetime.now(UTC)
            repositorios.notificar(sessao, "homologacao", rodada=rodada_id)
        logger.info("homologacao_terminada rodada=%s erro=%s", rodada_id, bool(erro))
