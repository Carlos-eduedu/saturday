"""Login com argon2id, bloqueio, sessão no banco e CSRF.

O cookie leva um token aleatório; o banco guarda só o sha256 dele, então um
vazamento da tabela não abre sessão. O CSRF é o HMAC do token com
``SESSAO_SEGREDO``: o front o recebe em ``GET /admin/eu`` e o devolve no header.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from saturday.dados.modelos import SessaoPainel, UsuarioPainel

DURACAO_SESSAO = timedelta(hours=8)
MAX_TENTATIVAS = 5
BLOQUEIO = timedelta(minutes=15)
PERFIS = ("atendente", "gestor")
TAMANHO_MINIMO_SENHA = 12

# Parâmetros padrão do argon2-cffi, que já usa a variante argon2id.
_hasher = PasswordHasher()
# Usado quando o e-mail não existe: gasta o mesmo tempo de uma senha errada,
# para que a resposta não revele quais e-mails estão cadastrados.
_HASH_FALSO = _hasher.hash(secrets.token_hex(16))


def agora() -> datetime:
    return datetime.now(UTC)


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


def _senha_confere(senha_hash: str, senha: str) -> bool:
    try:
        return _hasher.verify(senha_hash, senha)
    except VerificationError, InvalidHashError:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalizar_email(email: str) -> str:
    return email.strip().lower()


def nome_padrao(email: str) -> str:
    """Trecho do e-mail antes do `@`, para quem foi criado sem nome."""

    return normalizar_email(email).split("@", 1)[0][:80]


def criar_usuario(
    sessao: Session, email: str, senha: str, perfil: str, nome: str | None = None
) -> UsuarioPainel:
    if perfil not in PERFIS:
        raise ValueError(f"perfil inválido: {perfil}")
    usuario = UsuarioPainel(
        email=normalizar_email(email),
        nome=(nome or "").strip() or nome_padrao(email),
        senha_hash=gerar_hash(senha),
        perfil=perfil,
    )
    sessao.add(usuario)
    sessao.flush()
    return usuario


def autenticar(sessao: Session, email: str, senha: str) -> UsuarioPainel | None:
    """Confere a senha e conta a falha. ``None`` para qualquer recusa.

    E-mail inexistente, senha errada, conta bloqueada e conta desativada recebem
    a mesma resposta.
    A 5ª falha bloqueia por 15 min e derruba as sessões abertas.
    """

    usuario = sessao.scalar(
        select(UsuarioPainel)
        .where(UsuarioPainel.email == normalizar_email(email))
        .with_for_update()
    )
    if usuario is None or not usuario.ativo:
        _senha_confere(_HASH_FALSO, senha)
        return None

    momento = agora()
    if usuario.bloqueado_ate is not None:
        if usuario.bloqueado_ate > momento:
            return None
        usuario.bloqueado_ate = None
        usuario.tentativas_falhas = 0

    if not _senha_confere(usuario.senha_hash, senha):
        usuario.tentativas_falhas += 1
        if usuario.tentativas_falhas >= MAX_TENTATIVAS:
            usuario.bloqueado_ate = momento + BLOQUEIO
            encerrar_sessoes(sessao, usuario)
        sessao.flush()
        return None

    usuario.tentativas_falhas = 0
    if _hasher.check_needs_rehash(usuario.senha_hash):
        usuario.senha_hash = gerar_hash(senha)
    sessao.flush()
    return usuario


def abrir_sessao(sessao: Session, usuario: UsuarioPainel) -> str:
    """Grava a sessão e devolve o token que vai no cookie."""

    token = secrets.token_urlsafe(32)
    sessao.add(
        SessaoPainel(
            token_hash=_hash_token(token),
            usuario_id=usuario.id,
            expira_em=agora() + DURACAO_SESSAO,
        )
    )
    sessao.flush()
    return token


def usuario_da_sessao(sessao: Session, token: str) -> UsuarioPainel | None:
    return sessao.scalar(
        select(UsuarioPainel)
        .join(SessaoPainel, SessaoPainel.usuario_id == UsuarioPainel.id)
        .where(
            SessaoPainel.token_hash == _hash_token(token),
            SessaoPainel.expira_em > agora(),
            UsuarioPainel.ativo.is_(True),
        )
    )


def encerrar_sessao(sessao: Session, token: str) -> None:
    sessao.execute(delete(SessaoPainel).where(SessaoPainel.token_hash == _hash_token(token)))


def encerrar_sessoes(sessao: Session, usuario: UsuarioPainel) -> None:
    sessao.execute(delete(SessaoPainel).where(SessaoPainel.usuario_id == usuario.id))


def token_csrf(segredo: str, token: str) -> str:
    return hmac.new(segredo.encode(), token.encode(), hashlib.sha256).hexdigest()


def csrf_confere(segredo: str, token: str, recebido: str | None) -> bool:
    if not recebido:
        return False
    return hmac.compare_digest(token_csrf(segredo, token), recebido)
