"""Integrações: tokens de sistemas de fora no proxy da Granatech (decisão 0035).

O token sai uma vez, na criação, e o banco guarda só o sha256 dele, como na
sessão do painel. Cada token tem escopos; a rota pede o seu.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from saturday.dados.modelos import Auditoria, ChamadaIntegracao, Integracao, Outbox, UsuarioPainel
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


# ------------------------------------------------------------------ webhook (fase 2)

ENTREGAS_NA_TELA = 10


def url_aceita(url: str, *, local: bool) -> bool:
    """Só https; `http://localhost` vale fora de homolog e prod."""

    partes = urlsplit(url)
    if not partes.hostname:
        return False
    if partes.scheme == "https":
        return True
    return local and partes.scheme == "http" and partes.hostname in ("localhost", "127.0.0.1")


def _ativa(sessao: Session, integracao_id: uuid.UUID) -> Integracao:
    linha = sessao.get(Integracao, integracao_id)
    if linha is None or linha.revogada_em is not None:
        raise IntegracaoRecusada(404, "integração não encontrada ou revogada")
    return linha


def definir_webhook(
    sessao: Session, integracao_id: uuid.UUID, url: str | None, por: uuid.UUID
) -> None:
    """Grava ou apaga o endereço. Sem endereço, nenhum aviso novo entra na fila."""

    linha = _ativa(sessao, integracao_id)
    linha.webhook_url = url
    # Só o host na auditoria: o caminho pode levar um token do APP MEX.
    host = urlsplit(url).hostname if url else None
    auditar(sessao, por, "integracao_webhook", f"integracao:{integracao_id}", {"host": host})


def gerar_segredo(sessao: Session, integracao_id: uuid.UUID, por: uuid.UUID) -> str:
    """Segredo novo do HMAC, mostrado uma vez. O anterior para de valer na hora."""

    linha = _ativa(sessao, integracao_id)
    linha.webhook_segredo = "whsec_" + secrets.token_urlsafe(32)
    auditar(sessao, por, "integracao_segredo", f"integracao:{integracao_id}")
    return linha.webhook_segredo


def entregas(sessao: Session, integracao_id: uuid.UUID) -> list[Outbox]:
    return list(
        sessao.scalars(
            select(Outbox)
            .where(Outbox.integracao_id == integracao_id)
            .order_by(Outbox.id.desc())
            .limit(ENTREGAS_NA_TELA)
        ).all()
    )


# ------------------------------------------------------------------ histórico

# Quanto o Histórico do token guarda; o worker apaga o resto.
GUARDAR_CHAMADAS = timedelta(days=180)
# shortcut: o modal mostra só as últimas; paginar se alguém precisar de mais.
HISTORICO_NA_TELA = 200


def gravar_chamada_do_token(
    sessao: Session,
    integracao_id: uuid.UUID,
    metodo: str,
    rota: str,
    ids: dict[str, str],
    status: int,
    duracao_ms: int,
) -> None:
    sessao.add(
        ChamadaIntegracao(
            integracao_id=integracao_id,
            metodo=metodo,
            rota=rota[:200],
            ids=ids,
            status=status,
            duracao_ms=duracao_ms,
        )
    )


def podar_chamadas(sessao: Session, agora: datetime) -> None:
    sessao.execute(
        delete(ChamadaIntegracao).where(ChamadaIntegracao.criada_em < agora - GUARDAR_CHAMADAS)
    )


def historico(sessao: Session, integracao_id: uuid.UUID) -> list[dict[str, object]]:
    """Chamadas do token e o que o gestor fez com ele, do mais novo ao mais velho."""

    chamadas = sessao.scalars(
        select(ChamadaIntegracao)
        .where(ChamadaIntegracao.integracao_id == integracao_id)
        .order_by(ChamadaIntegracao.criada_em.desc(), ChamadaIntegracao.id.desc())
        .limit(HISTORICO_NA_TELA)
    ).all()
    gestao = sessao.execute(
        select(Auditoria, UsuarioPainel.nome)
        .outerjoin(UsuarioPainel, UsuarioPainel.id == Auditoria.usuario_id)
        .where(Auditoria.alvo == f"integracao:{integracao_id}")
        .order_by(Auditoria.criada_em.desc())
        .limit(HISTORICO_NA_TELA)
    ).all()
    linhas: list[tuple[datetime, dict[str, object]]] = [
        (
            c.criada_em,
            {
                "tipo": "chamada",
                "metodo": c.metodo,
                "rota": c.rota,
                "ids": c.ids,
                "status": c.status,
                "duracao_ms": c.duracao_ms,
            },
        )
        for c in chamadas
    ] + [
        (a.criada_em, {"tipo": "gestao", "acao": a.acao, "por": nome, "detalhe": a.detalhe})
        for a, nome in gestao
    ]
    linhas.sort(key=lambda linha: linha[0], reverse=True)
    return [{"em": em.isoformat(), **linha} for em, linha in linhas[:HISTORICO_NA_TELA]]
