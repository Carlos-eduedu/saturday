"""Telefone fixado das instâncias da Evolution (decisão 0010)."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import Conversa, Instancia


def fixar_telefone(sessao: Session, nome: str, telefone: str) -> str:
    """Grava o telefone na primeira conexão; devolve o que ficou fixado.

    Concorrência: dois `open` simultâneos não sobrescrevem um ao outro.
    """

    sessao.execute(
        insert(Instancia)
        .values(nome=nome, telefone=telefone)
        .on_conflict_do_nothing(index_elements=["nome"])
    )
    return str(sessao.scalars(select(Instancia.telefone).where(Instancia.nome == nome)).one())


def soltar(sessao: Session, nome: str) -> None:
    """Apagar a instância libera o nome para outro telefone.

    As conversas dela ficam sem instância até o cliente escrever para outra
    (`obter_ou_criar_conversa` grava a nova): uma instância recriada com o mesmo
    nome em outro celular não herda as conversas.
    """

    sessao.execute(delete(Instancia).where(Instancia.nome == nome))
    sessao.execute(
        update(Conversa)
        .where(Conversa.canal == "evolution", Conversa.phone_number_id == nome)
        .values(phone_number_id=None)
    )


def telefones(sessao: Session) -> dict[str, str]:
    return {i.nome: i.telefone for i in sessao.scalars(select(Instancia))}
