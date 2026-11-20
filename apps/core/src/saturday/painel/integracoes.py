"""Integrações: tokens de sistemas de fora no proxy da Granatech (decisão 0035).

O token sai uma vez, na criação, e o banco guarda só o sha256 dele, como na
sessão do painel. Cada token tem escopos; a rota pede o seu.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from saturday.dados.modelos import Integracao
from saturday.painel.auditoria import auditar

ESCOPOS = ("leitura", "revelar", "acoes", "operacoes", "homologacao")
PREFIXO = "sat_"
# `ultimo_uso_em` é para o gestor ver se o token está em uso; minuto basta.
GRAVAR_USO_A_CADA = timedelta(minutes=1)


class IntegracaoRecusada(Exception):
    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def criar(
    sessao: Session, nome: str, escopos: list[str], criada_por: uuid.UUID
) -> tuple[Integracao, str]:
    """Nova integração e o token dela, que não volta a aparecer."""

    token = PREFIXO + secrets.token_urlsafe(32)
    linha = Integracao(
        nome=nome.strip(),
        token_hash=_hash(token),
        escopos=[e for e in ESCOPOS if e in escopos],
        criada_por=criada_por,
    )
    sessao.add(linha)
    sessao.flush()
    auditar(
        sessao,
        criada_por,
        "integracao_criar",
        f"integracao:{linha.id}",
        {"nome": linha.nome, "escopos": linha.escopos},
    )
    return linha, token


def revogar(sessao: Session, integracao_id: uuid.UUID, por: uuid.UUID) -> bool:
    """Revoga de vez; `False` se não existe ou já estava revogada."""

    revogada = sessao.execute(
        update(Integracao)
        .where(Integracao.id == integracao_id, Integracao.revogada_em.is_(None))
        .values(revogada_em=func.now())
        .returning(Integracao.id)
    ).scalar_one_or_none()
    if revogada is None:
        return False
    auditar(sessao, por, "integracao_revogar", f"integracao:{integracao_id}")
    return True


def autenticar(sessao: Session, token: str, escopo: str, agora: datetime) -> Integracao:
    """A integração dona do token, se ativa e com o escopo; senão recusa."""

    linha = (
        sessao.scalars(select(Integracao).where(Integracao.token_hash == _hash(token))).first()
        if token
        else None
    )
    if linha is None or linha.revogada_em is not None:
        raise IntegracaoRecusada(401, "não autorizado")
    if escopo not in linha.escopos:
        raise IntegracaoRecusada(403, f"token sem o escopo {escopo}")
    if linha.ultimo_uso_em is None or agora - linha.ultimo_uso_em >= GRAVAR_USO_A_CADA:
        linha.ultimo_uso_em = agora
    return linha
