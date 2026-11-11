"""Links curtos da biometria: ``https://{DOMINIO_PUBLICO}/l/{codigo}``."""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from saturday.dados.modelos import LinkCurto


def criar(sessao: Session, *, id_proposta: str, url: str) -> str:
    codigo = secrets.token_urlsafe(6)
    sessao.add(LinkCurto(codigo=codigo, id_proposta=id_proposta, url=url))
    sessao.flush()
    return codigo


def buscar(sessao: Session, codigo: str) -> LinkCurto | None:
    return sessao.get(LinkCurto, codigo)


def endereco(dominio: str, codigo: str) -> str:
    return f"https://{dominio.strip().rstrip('/')}/l/{codigo}"
