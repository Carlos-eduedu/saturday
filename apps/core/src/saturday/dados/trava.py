"""Trava por conversa no próprio Postgres.

O ``threading.Lock`` antigo só valia dentro de um processo. Com dois workers, a
serialização precisa morar no banco: ``pg_advisory_xact_lock`` é liberada
automaticamente no commit ou no rollback, então não existe caminho de código que
esqueça de soltar a trava.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from saturday.dados.modelos import Conversa

_MASCARA_64 = (1 << 64) - 1


def chave_trava(conversation_id: str) -> int:
    """Deriva um int64 assinado e estável a partir do ``conversation_id``.

    ``blake2b`` em vez de ``hashtext()``: o hash do Postgres é de 32 bits e não
    tem contrato de estabilidade entre versões. Como a chave é calculada em
    Python, ela é testável e igual em qualquer processo e linguagem.
    """

    digest = hashlib.blake2b(conversation_id.encode("utf-8"), digest_size=8).digest()
    bits = int.from_bytes(digest, "big") & _MASCARA_64
    return bits - (1 << 64) if bits >= (1 << 63) else bits


def travar_conversa(sessao: Session, conversation_id: str) -> None:
    """Espera a trava da conversa até o fim da transação atual.

    A chamada bloqueia quando outro worker está com a mesma conversa: é essa
    espera que impede dois turnos simultâneos sobre o mesmo estado.
    """

    sessao.execute(
        text("SELECT pg_advisory_xact_lock(:chave)"),
        {"chave": chave_trava(conversation_id)},
    )


def travar_e_reler(sessao: Session, conversation_id: str) -> Conversa:
    """Trava a conversa e a relê já sob a trava.

    `populate_existing` descarta a cópia que a sessão já tinha: quem decide com
    ela decide com o estado de antes de o outro processo terminar.
    """

    travar_conversa(sessao, conversation_id)
    return sessao.scalars(
        select(Conversa)
        .where(Conversa.conversation_id == conversation_id)
        .execution_options(populate_existing=True)
    ).one()


def tentar_trava(sessao: Session, chave: str) -> bool:
    """Pega a trava de ``chave`` se estiver livre, sem esperar.

    Vale até o fim da transação, como a da conversa. Serve a quem prefere
    recusar a esperar: a segunda ação do gestor no mesmo item (decisão 0024).
    """

    return bool(
        sessao.scalar(
            text("SELECT pg_try_advisory_xact_lock(:chave)"), {"chave": chave_trava(chave)}
        )
    )
