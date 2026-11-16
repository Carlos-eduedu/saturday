"""Processamento dos eventos de entrada pelo worker.

O webhook só grava. Aqui o evento vira turno (ou atualização de status de
entrega), sempre com a trava da conversa no serviço. Erro que não é de conteúdo
volta para a fila; depois do limite, o evento é marcado como falho e fica para
inspeção.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.canais.base import Envio, OrigemCanal
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.canais.whatsapp import webhook as parser
from saturday.canais.whatsapp.entrada import Entrada, EntradaWhatsApp, prefixo_do_canal
from saturday.dados import eventos as fila
from saturday.dados import repositorios
from saturday.dados.modelos import EventoRecebido
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as eventos_granatech
from saturday.jobs import icred as eventos_icred
from saturday.jobs import instancias as eventos_instancias
from saturday.settings import Settings

logger = logging.getLogger(__name__)

ORIGEM_GRANATECH = "granatech"
ORIGEM_EVOLUTION = "evolution"
ORIGEM_ICRED = "icred"


def processar(
    fabrica: sessionmaker[Session],
    servico: AgentService,
    entrada: EntradaWhatsApp,
    settings: Settings,
    granatech: ClienteGranatech | None = None,
    evolution: EntradaWhatsApp | None = None,
    cliente_evolution: EvolutionClient | None = None,
) -> int:
    """Reivindica um lote de eventos e processa. Devolve quantos tentou."""

    with abrir_sessao(fabrica) as reserva:
        linhas = fila.reivindicar(reserva, settings.eventos_lote)

    if not linhas:
        return 0

    for linha in linhas:
        try:
            if linha.origem == ORIGEM_GRANATECH:
                eventos_granatech.aplicar(fabrica, granatech, linha.payload or {}, servico)
            elif linha.origem == ORIGEM_ICRED:
                eventos_icred.aplicar(fabrica, linha.payload or {}, servico)
            elif (
                linha.origem == ORIGEM_EVOLUTION and (linha.payload or {}).get("tipo") == "conexao"
            ):
                eventos_instancias.aplicar(fabrica, cliente_evolution, linha.payload or {})
            elif linha.origem == ORIGEM_EVOLUTION:
                if evolution is None:
                    raise RuntimeError("evento da Evolution com o canal desligado")
                _processar_um(fabrica, servico, evolution, linha)
            else:
                _processar_um(fabrica, servico, entrada, linha)
        except Exception as exc:  # noqa: BLE001 - o erro fica na linha, não derruba o laço
            logger.exception("evento_falhou id=%s", linha.id)
            desistiu = _registrar_resultado(
                fabrica,
                linha.id,
                erro=f"{type(exc).__name__}: {exc}",
                settings=settings,
            )
            if desistiu and linha.origem in (ORIGEM_GRANATECH, ORIGEM_ICRED):
                _avisar_desistencia(fabrica, servico, linha)
        else:
            _registrar_resultado(fabrica, linha.id, erro="", settings=settings)

    return len(linhas)


def _tipo(linha: EventoRecebido) -> object:
    return (linha.payload or {}).get("tipo")


def _registrar_resultado(
    fabrica: sessionmaker[Session],
    linha_id: int,
    *,
    erro: str,
    settings: Settings,
) -> bool:
    """Grava o resultado na linha. Devolve se a fila desistiu do evento."""

    with abrir_sessao(fabrica) as sessao:
        atual = sessao.get(EventoRecebido, linha_id)
        if atual is None:
            return False
        if not erro:
            fila.marcar_processado(sessao, atual)
            return False
        desistir = atual.tentativas >= settings.eventos_max_tentativas
        fila.marcar_falha(sessao, atual, erro=erro, desistir=desistir)
        return desistir


def _avisar_desistencia(
    fabrica: sessionmaker[Session], servico: AgentService, linha: EventoRecebido
) -> None:
    """Sem isto o cliente fica esperando um evento que ninguém mais vai tentar."""

    modulo = eventos_icred if linha.origem == ORIGEM_ICRED else eventos_granatech
    try:
        modulo.desistir(fabrica, linha.payload or {}, servico)
    except Exception:  # noqa: BLE001 - o aviso não derruba o laço
        logger.exception("aviso_de_desistencia_falhou id=%s", linha.id)


def _processar_um(
    fabrica: sessionmaker[Session],
    servico: AgentService,
    entrada: EntradaWhatsApp,
    linha: EventoRecebido,
) -> None:
    payload = linha.payload or {}

    if payload.get("tipo") == "status":
        _aplicar_status(fabrica, payload)
        return

    evento = _evento_de(payload)
    # Recibo de leitura antes de processar: o cliente vê que foi recebido mesmo
    # quando o turno demora ou cai para a equipe.
    entrada.marcar_lida(evento)
    preparada = entrada.preparar(evento)
    if preparada.resposta_local is not None:
        _enfileirar_resposta(fabrica, entrada.canal, evento, preparada)
        return
    if preparada.pedido is None:
        # Tipo só registrado (localização, figurinha, reação…).
        return

    servico.process_message(
        preparada.pedido,
        OrigemCanal(
            canal=entrada.canal,
            telefone=evento.numero,
            phone_number_id=evento.phone_number_id,
        ),
        historico=preparada.historico or None,
    )


def _aplicar_status(fabrica: sessionmaker[Session], payload: dict[str, Any]) -> None:
    wamid = str(payload.get("wamid") or "")
    situacao = str(payload.get("status") or "")
    if not wamid or not situacao:
        return
    with abrir_sessao(fabrica) as sessao:
        if not repositorios.atualizar_status(sessao, wamid=wamid, status=situacao):
            logger.info("status_de_mensagem_desconhecida wamid=%s", wamid)


def _enfileirar_resposta(
    fabrica: sessionmaker[Session],
    canal: str,
    evento: parser.Evento,
    preparada: Entrada,
) -> None:
    """Resposta que não passa pelo grafo (áudio ilegível, mídia recusada).

    A mensagem do cliente também é gravada, com o áudio como anexo: sem isso
    o painel não mostrava o que ele mandou, só a nossa resposta.
    """

    texto = preparada.resposta_local or ""

    with abrir_sessao(fabrica) as sessao:
        conversa = repositorios.obter_ou_criar_conversa(
            sessao,
            prefixo_do_canal(evento.numero, canal),
            canal=canal,
            telefone=evento.numero,
            phone_number_id=evento.phone_number_id,
        )
        # O cliente escreveu: a janela reabre mesmo quando a resposta não passa
        # pelo grafo (áudio ilegível, mídia recusada).
        repositorios.marcar_entrada(conversa)
        repositorios.registrar_entrada(
            sessao,
            conversa,
            message_id=evento.evento_id,
            conteudo=preparada.conteudo or evento.texto or "[mensagem]",
            anexos=preparada.historico or None,
        )
        mensagem_id = repositorios.registrar_saida(sessao, conversa, conteudo=texto)
        enfileirar(
            sessao,
            conversa_id=conversa.id,
            canal=canal,
            payload={
                **Envio(
                    conversation_id=conversa.conversation_id,
                    numero=evento.numero,
                    phone_number_id=evento.phone_number_id,
                    texto=texto,
                    mensagem_id=mensagem_id,
                ).para_payload(),
                "status": "answered",
            },
        )


def _evento_de(payload: dict[str, Any]) -> parser.Evento:
    midia_bruta = payload.get("midia")
    midia = None
    if isinstance(midia_bruta, dict):
        midia = parser.Midia(
            id=str(midia_bruta.get("id") or ""),
            mime_type=str(midia_bruta.get("mime_type") or ""),
            nome=midia_bruta.get("nome"),
        )

    tipo = payload.get("tipo")
    return parser.Evento(
        tipo="status" if tipo == "status" else "mensagem",
        evento_id=str(payload.get("evento_id") or ""),
        wamid=str(payload.get("wamid") or ""),
        numero=str(payload.get("numero") or ""),
        phone_number_id=str(payload.get("phone_number_id") or ""),
        texto=str(payload.get("texto") or ""),
        tipo_midia=str(payload.get("tipo_midia") or ""),
        midia=midia,
        status=payload.get("status"),
        referral=payload.get("referral"),
        roda_turno=bool(payload.get("roda_turno", True)),
    )
