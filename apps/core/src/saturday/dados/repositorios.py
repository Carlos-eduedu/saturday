"""Consultas e gravações das tabelas usadas nesta fase."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import Conversa, Mensagem


def obter_ou_criar_conversa(
    sessao: Session,
    conversation_id: str,
    *,
    canal: str = "chat",
) -> Conversa:
    conversa = sessao.scalar(select(Conversa).where(Conversa.conversation_id == conversation_id))
    if conversa is not None:
        return conversa
    conversa = Conversa(conversation_id=conversation_id, canal=canal)
    sessao.add(conversa)
    sessao.flush()
    return conversa


def registrar_entrada(
    sessao: Session,
    conversa: Conversa,
    *,
    message_id: str | None,
    conteudo: str,
) -> bool:
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
) -> None:
    sessao.add(
        Mensagem(
            conversa_id=conversa.id,
            direcao="saida",
            message_id=message_id,
            conteudo=conteudo,
        )
    )
    sessao.flush()
