"""Prova do "SIM" do cliente (AGENTS.md, regra 3).

Gravada em transação própria, antes da ação que ela autoriza: se a consulta for
aberta, a prova já está no banco.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Consentimento
from saturday.dados.sessao import sessao as abrir_sessao


def gravar_prova(
    fabrica: sessionmaker[Session],
    *,
    conversa_id: uuid.UUID | None,
    tipo: str,
    texto_mostrado: str,
    versao: str,
    resposta_literal: str,
    wamid: str | None,
    cpf: str,
) -> int:
    with abrir_sessao(fabrica) as sessao:
        prova = Consentimento(
            conversa_id=conversa_id,
            tipo=tipo,
            texto_mostrado=texto_mostrado,
            versao=versao,
            resposta_literal=resposta_literal,
            wamid=wamid,
            cpf=cpf,
        )
        sessao.add(prova)
        sessao.flush()
        return prova.id


def existe_prova(sessao: Session, *, conversa_id: uuid.UUID | None, tipo: str, cpf: str) -> bool:
    return (
        sessao.scalars(
            select(Consentimento.id).where(
                Consentimento.conversa_id == conversa_id,
                Consentimento.tipo == tipo,
                Consentimento.cpf == cpf,
            )
        ).first()
        is not None
    )
