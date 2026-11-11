"""Consultas e gravações das tabelas usadas nesta fase."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import Conversa, Mensagem


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
) -> bool:
    marcar_entrada(conversa)
    """Grava a mensagem do cliente. ``False`` quando o ``message_id`` já existe.

    A decisão é do banco, não de uma lista em memória: ``ON CONFLICT DO NOTHING``
    sobre a chave única é o que vale com dois workers ao mesmo tempo.
    """

    if message_id is None:
        sessao.add(Mensagem(conversa_id=conversa.id, direcao="entrada", conteudo=conteudo))
        sessao.flush()
        return True

    resultado = sessao.execute(
        insert(Mensagem)
        .values(
            conversa_id=conversa.id,
            direcao="entrada",
            message_id=message_id,
            conteudo=conteudo,
        )
        .on_conflict_do_nothing(index_elements=["conversa_id", "direcao", "message_id"])
        .returning(Mensagem.id)
    )
    return resultado.scalar_one_or_none() is not None


def registrar_saida(
    sessao: Session,
    conversa: Conversa,
    *,
    conteudo: str,
    message_id: str | None = None,
) -> int:
    """Grava a resposta e devolve o id.

    O id volta para o outbox: quando a Meta confirmar o envio, é nesta linha que
    o `wamid` e o status de entrega vão ser gravados.
    """

    linha = Mensagem(
        conversa_id=conversa.id,
        direcao="saida",
        message_id=message_id,
        conteudo=conteudo,
    )
    sessao.add(linha)
    sessao.flush()
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
    return True
