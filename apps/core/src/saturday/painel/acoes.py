"""Regras das ações sobre uma conversa: quem pode assumir, devolver, transferir e enviar.

Cada ação roda sob a trava da conversa (a mesma do turno da IA), muda o estado
de atendimento e grava a auditoria na mesma transação.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import CANAIS_WHATSAPP
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS
from saturday.dados import repositorios
from saturday.dados.modelos import (
    Auditoria,
    ConsultaGranatech,
    Conversa,
    PropostaGranatech,
    UsuarioPainel,
)
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import travar_conversa
from saturday.painel import midia
from saturday.painel.auditoria import auditar
from saturday.storage.base import Storage

# Modelos que o atendente pode mandar: utilidade e sem botão de link.
# TODO: variáveis de modelo quando os textos forem cadastrados na Meta; os
# links `/l/{codigo}` só existem na Fase 6.
MODELOS_DO_PAINEL = tuple(
    nome
    for nome, modelo in MODELOS.items()
    if modelo.categoria == "utilidade" and not modelo.tem_link
)


class AcaoRecusada(Exception):
    """A ação não vale para este usuário ou para o estado da conversa."""

    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


@contextmanager
def conversa_travada(
    fabrica: sessionmaker[Session], conversa_id: uuid.UUID
) -> Iterator[tuple[Session, Conversa]]:
    """Abre a transação, trava a conversa e a relê já sob a trava."""

    with abrir_sessao(fabrica) as sessao:
        conversation_id = sessao.scalar(
            select(Conversa.conversation_id).where(Conversa.id == conversa_id)
        )
        if conversation_id is None:
            raise AcaoRecusada(404, "conversa não encontrada")
        travar_conversa(sessao, conversation_id)
        conversa = sessao.scalars(
            select(Conversa)
            .where(Conversa.id == conversa_id)
            .execution_options(populate_existing=True)
        ).one()
        yield sessao, conversa


# Ações que mudam o atendimento; a última delas é a única que se desfaz.
ACOES_DE_ATENDIMENTO = ("assumir", "devolver", "transferir", "desfazer")
# Folga sobre os 5 s em que o painel mostra "Desfazer".
PRAZO_DESFAZER = timedelta(seconds=15)


def _estado(conversa: Conversa) -> dict[str, Any]:
    """O atendimento de agora, para a auditoria e para o desfazer."""

    dono = conversa.atendente_id
    return {"antes": conversa.atendimento, "de": str(dono) if dono else None}


def _exigir_dono(conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    if gestor or conversa.atendente_id == usuario_id:
        return
    raise AcaoRecusada(403, "a conversa é de outro atendente")


def assumir(sessao: Session, conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    """Atendente assume da IA ou do handoff; só o gestor toma de outro atendente."""

    if conversa.atendimento == "assumida":
        if conversa.atendente_id == usuario_id:
            return
        _exigir_dono(conversa, usuario_id, gestor)
    antes = _estado(conversa)
    repositorios.mudar_atendimento(sessao, conversa, "assumida", atendente_id=usuario_id)
    auditar(sessao, usuario_id, "assumir", str(conversa.id), antes)


def devolver(sessao: Session, conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    if conversa.atendimento == "ia":
        return
    if conversa.atendimento == "assumida":
        _exigir_dono(conversa, usuario_id, gestor)
    antes = _estado(conversa)
    repositorios.mudar_atendimento(sessao, conversa, "ia")
    auditar(sessao, usuario_id, "devolver", str(conversa.id), antes)


def desfazer(sessao: Session, conversa: Conversa, usuario_id: uuid.UUID) -> None:
    """Volta a conversa ao estado de antes do último assumir ou devolver de quem pede.

    Só vale por `PRAZO_DESFAZER` e enquanto nada mais mexeu no atendimento: a
    ação desfeita precisa ser a última da conversa e o estado, o que ela deixou.
    """

    ultima = sessao.scalars(
        select(Auditoria)
        .where(Auditoria.alvo == str(conversa.id), Auditoria.acao.in_(ACOES_DE_ATENDIMENTO))
        .order_by(Auditoria.id.desc())
        .limit(1)
    ).first()
    recente = (
        ultima is not None
        and ultima.usuario_id == usuario_id
        and ultima.acao in ("assumir", "devolver")
        and sessao.scalar(select(func.now() - ultima.criada_em <= PRAZO_DESFAZER))
    )
    if ultima is None or not recente:
        raise AcaoRecusada(409, "não dá mais para desfazer")
    deixou = ("assumida", usuario_id) if ultima.acao == "assumir" else ("ia", None)
    if (conversa.atendimento, conversa.atendente_id) != deixou:
        raise AcaoRecusada(409, "não dá mais para desfazer: a conversa já mudou")

    antes = ultima.detalhe or {}
    dono = uuid.UUID(antes["de"]) if antes.get("de") else None
    if antes.get("antes") == "assumida":
        destino = sessao.get(UsuarioPainel, dono) if dono else None
        if destino is None or not destino.ativo:
            raise AcaoRecusada(409, "não dá mais para desfazer: quem estava com ela saiu")
    repositorios.mudar_atendimento(sessao, conversa, str(antes.get("antes")), atendente_id=dono)
    auditar(sessao, usuario_id, "desfazer", str(conversa.id), {"acao": ultima.acao})


def transferir(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    gestor: bool,
    destino_id: uuid.UUID,
) -> None:
    if conversa.atendimento != "assumida":
        raise AcaoRecusada(409, "só conversa assumida pode ser transferida")
    _exigir_dono(conversa, usuario_id, gestor)
    destino = sessao.get(UsuarioPainel, destino_id)
    if destino is None or not destino.ativo:
        raise AcaoRecusada(404, "atendente de destino não encontrado")
    anterior = conversa.atendente_id
    repositorios.mudar_atendimento(sessao, conversa, "assumida", atendente_id=destino_id)
    auditar(
        sessao,
        usuario_id,
        "transferir",
        str(conversa.id),
        {"de": str(anterior), "para": str(destino_id)},
    )


def editar_ficha(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    gestor: bool,
    campos: list[str],
) -> None:
    """Confere se a correção da ficha cabe e deixa o rastro, sem os valores.

    CPF e conta param de mudar quando o banco já os recebeu: o CPF depois da
    consulta (muda a cota e a consulta feita), a conta depois da proposta (aí
    só pela Granatech, em "corrigir conta").
    """

    _exigir_dono(conversa, usuario_id, gestor)
    if not campos:
        raise AcaoRecusada(422, "nada para mudar")
    if "cpf" in campos and sessao.scalar(
        select(ConsultaGranatech.id).where(ConsultaGranatech.conversa_id == conversa.id).limit(1)
    ):
        raise AcaoRecusada(409, "o CPF não muda depois da consulta na Granatech")
    if "conta" in campos and sessao.scalar(
        select(PropostaGranatech.id).where(PropostaGranatech.conversa_id == conversa.id).limit(1)
    ):
        raise AcaoRecusada(409, "a proposta já foi criada: corrija a conta pela aba Granatech")
    auditar(sessao, usuario_id, "conversa:editar_ficha", str(conversa.id), {"campos": campos})
    repositorios.notificar(sessao, "conversa", conversa=conversa.id)


def _conferir_envio(conversa: Conversa, usuario_id: uuid.UUID) -> None:
    """Só quem assumiu responde, e o painel só envia pelo WhatsApp."""

    if conversa.atendimento != "assumida" or conversa.atendente_id != usuario_id:
        raise AcaoRecusada(409, "assuma a conversa antes de responder")
    if (
        conversa.canal not in CANAIS_WHATSAPP
        or not conversa.telefone
        or not conversa.phone_number_id
    ):
        raise AcaoRecusada(409, "o painel só envia pelo WhatsApp")


def _payload(conversa: Conversa, mensagem_id: int, texto: str) -> dict[str, Any]:
    return {
        "conversation_id": conversa.conversation_id,
        "numero": conversa.telefone,
        "phone_number_id": conversa.phone_number_id,
        "answer": texto,
        "mensagem_id": mensagem_id,
    }


def enviar(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    *,
    texto: str | None,
    modelo: str | None,
) -> int:
    """Grava a mensagem do atendente e o envio no outbox, na mesma transação."""

    _conferir_envio(conversa, usuario_id)
    if (texto is None) == (modelo is None):
        raise AcaoRecusada(422, "envie texto ou modelo")
    # Janela e modelos são da Meta; a Evolution só manda texto (decisão 0009).
    meta = conversa.canal == "whatsapp"
    if modelo is not None and (not meta or modelo not in MODELOS_DO_PAINEL):
        raise AcaoRecusada(422, "modelo indisponível no painel")
    if (
        meta
        and texto is not None
        and not janela_aberta(conversa.ultima_entrada_em, datetime.now(UTC))
    ):
        raise AcaoRecusada(409, "janela de 24 h fechada: envie um modelo")

    mensagem_id = repositorios.registrar_saida(
        sessao,
        conversa,
        conteudo=texto if texto is not None else f"[modelo {modelo}]",
        autor="atendente",
        usuario_id=usuario_id,
    )
    payload = _payload(conversa, mensagem_id, texto or "")
    if modelo is not None:
        payload["modelo"] = modelo
    enfileirar(sessao, conversa_id=conversa.id, canal=conversa.canal, payload=payload)
    auditar(
        sessao,
        usuario_id,
        "enviar_mensagem",
        str(conversa.id),
        {"mensagem_id": mensagem_id, "modelo": modelo},
    )
    return mensagem_id


def enviar_anexo(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    storage: Storage,
    *,
    dados: bytes,
    mime_type: str,
    nome: str,
    legenda: str,
) -> int:
    """Guarda o arquivo no storage e enfileira o envio; o outbox leva só a chave.

    Mesmas regras do texto: só quem assumiu, só WhatsApp e, na Meta, só com a
    janela aberta (fora dela a Meta recusa qualquer coisa que não seja modelo).
    """

    _conferir_envio(conversa, usuario_id)
    try:
        tipo = midia.conferir(dados, mime_type)
    except midia.MidiaRecusada as exc:
        raise AcaoRecusada(exc.status, exc.detalhe) from exc
    if conversa.canal == "whatsapp" and not janela_aberta(
        conversa.ultima_entrada_em, datetime.now(UTC)
    ):
        raise AcaoRecusada(409, "janela de 24 h fechada: envie um modelo")

    extensao = midia.EXTENSAO[mime_type]
    chave = storage.salvar(
        dados,
        mime_type=mime_type,
        chave=f"{conversa.canal}/{conversa.telefone}/painel-{uuid.uuid4().hex}.{extensao}",
    )
    anexo = {"chave": chave, "mime_type": mime_type, "nome": nome}
    mensagem_id = repositorios.registrar_saida(
        sessao,
        conversa,
        conteudo=legenda or f"[{midia.ROTULO[tipo]} {nome}]",
        autor="atendente",
        usuario_id=usuario_id,
        anexos=[anexo],
    )
    payload = _payload(conversa, mensagem_id, legenda)
    payload["midia"] = {**anexo, "tipo": tipo}
    enfileirar(sessao, conversa_id=conversa.id, canal=conversa.canal, payload=payload)
    auditar(
        sessao,
        usuario_id,
        "enviar_anexo",
        str(conversa.id),
        {"mensagem_id": mensagem_id, "tipo": tipo, "bytes": len(dados)},
    )
    return mensagem_id
