"""Consultas e gravações das tabelas usadas nesta fase."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import Alerta, Conversa, Mensagem

# Canal do `LISTEN` da API (`web/eventos.py`). O aviso leva só tipo e IDs:
# nada de dado pessoal passa por ele.
CANAL_PAINEL = "painel"


def notificar(sessao: Session, tipo: str, **ids: Any) -> None:
    """Avisa o painel. O Postgres só entrega no commit: rollback não avisa."""

    carga = json.dumps({"tipo": tipo, **{k: str(v) for k, v in ids.items()}})
    sessao.execute(select(func.pg_notify(CANAL_PAINEL, carga)))


def obter_ou_criar_conversa(
    sessao: Session,
    conversation_id: str,
    *,
    canal: str = "chat",
    telefone: str | None = None,
    phone_number_id: str | None = None,
) -> Conversa:
    conversa = sessao.scalar(select(Conversa).where(Conversa.conversation_id == conversation_id))
    if conversa is None:
        conversa = Conversa(
            conversation_id=conversation_id,
            canal=canal,
            telefone=telefone,
            phone_number_id=phone_number_id,
        )
        sessao.add(conversa)
        sessao.flush()
        return conversa

    # O cliente fica preso ao número em que escreveu; o telefone só é gravado
    # uma vez, para não reescrever a cada turno.
    if telefone and conversa.telefone != telefone:
        conversa.telefone = telefone
    if phone_number_id:
        conversa.phone_number_id = phone_number_id
    return conversa


def marcar_entrada(conversa: Conversa) -> None:
    """Toda mensagem do cliente reabre a janela de 24 h do canal."""

    conversa.ultima_entrada_em = func.now()


def registrar_entrada(
    sessao: Session,
    conversa: Conversa,
    *,
    message_id: str | None,
    conteudo: str,
    anexos: list[dict[str, Any]] | None = None,
) -> bool:
    """Grava a mensagem do cliente. ``False`` quando o ``message_id`` já existe.

    A decisão é do banco, não de uma lista em memória: ``ON CONFLICT DO NOTHING``
    sobre a chave única é o que vale com dois workers ao mesmo tempo.
    """

    marcar_entrada(conversa)
    if message_id is None:
        sessao.add(
            Mensagem(
                conversa_id=conversa.id,
                direcao="entrada",
                autor="cliente",
                conteudo=conteudo,
                anexos=anexos,
            )
        )
        sessao.flush()
        notificar(sessao, "mensagem", conversa=conversa.id)
        return True

    resultado = sessao.execute(
        insert(Mensagem)
        .values(
            conversa_id=conversa.id,
            direcao="entrada",
            autor="cliente",
            message_id=message_id,
            conteudo=conteudo,
            anexos=anexos,
        )
        .on_conflict_do_nothing(index_elements=["conversa_id", "direcao", "message_id"])
        .returning(Mensagem.id)
    )
    inserida = resultado.scalar_one_or_none() is not None
    if inserida:
        notificar(sessao, "mensagem", conversa=conversa.id)
    return inserida


def registrar_saida(
    sessao: Session,
    conversa: Conversa,
    *,
    conteudo: str,
    message_id: str | None = None,
    autor: str = "ia",
    usuario_id: uuid.UUID | None = None,
) -> int:
    """Grava a resposta e devolve o id.

    O id volta para o outbox: quando a Meta confirmar o envio, é nesta linha que
    o `wamid` e o status de entrega vão ser gravados.
    """

    linha = Mensagem(
        conversa_id=conversa.id,
        direcao="saida",
        autor=autor,
        usuario_id=usuario_id,
        message_id=message_id,
        conteudo=conteudo,
    )
    sessao.add(linha)
    sessao.flush()
    notificar(sessao, "mensagem", conversa=conversa.id)
    return linha.id


def buscar_conversa(sessao: Session, conversation_id: str) -> Conversa | None:
    return sessao.scalar(select(Conversa).where(Conversa.conversation_id == conversation_id))


def marcar_envio(
    sessao: Session,
    mensagem_id: int,
    *,
    wamid: str | None,
    status: str,
) -> None:
    """Guarda a identificação da Meta na mensagem que a originou."""

    linha = sessao.get(Mensagem, mensagem_id)
    if linha is None:
        return
    if wamid:
        linha.wamid = wamid
    linha.status_entrega = status
    sessao.flush()


def atualizar_status(sessao: Session, *, wamid: str, status: str) -> bool:
    """Aplica um `statuses` do webhook. ``False`` se a mensagem é desconhecida."""

    linha = sessao.scalar(select(Mensagem).where(Mensagem.wamid == wamid))
    if linha is None:
        return False
    linha.status_entrega = status
    sessao.flush()
    notificar(sessao, "mensagem", conversa=linha.conversa_id)
    return True


def mudar_atendimento(
    sessao: Session,
    conversa: Conversa,
    atendimento: str,
    *,
    atendente_id: uuid.UUID | None = None,
) -> None:
    """Muda quem responde a conversa: `ia`, `handoff` ou `assumida`."""

    conversa.atendimento = atendimento
    conversa.atendente_id = atendente_id if atendimento == "assumida" else None
    conversa.atendimento_em = func.now()
    sessao.flush()
    notificar(sessao, "conversa", conversa=conversa.id)


def abrir_alerta(
    sessao: Session,
    tipo: str,
    *,
    conversa_id: uuid.UUID | None = None,
    detalhe: dict[str, Any] | None = None,
) -> Alerta:
    alerta = Alerta(tipo=tipo, conversa_id=conversa_id, detalhe=detalhe)
    sessao.add(alerta)
    sessao.flush()
    notificar(sessao, "alerta", alerta=alerta.id)
    return alerta
