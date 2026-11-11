"""Login, bloqueio, sessão e CSRF do painel. Os de banco exigem Postgres."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from saturday.dados.modelos import SessaoPainel
from saturday.dados.sessao import sessao as abrir
from saturday.painel import sessoes
from saturday.painel.cli import criar_usuario_cli

SENHA = "senha-bem-comprida-1"


def _usuario(fabrica, email="ana@exemplo.test", perfil="atendente"):
    with abrir(fabrica) as s:
        return sessoes.criar_usuario(s, email, SENHA, perfil).id


def _login(fabrica, email="ana@exemplo.test", senha=SENHA):
    with abrir(fabrica) as s:
        usuario = sessoes.autenticar(s, email, senha)
        return usuario.id if usuario else None


def test_hash_e_argon2id():
    assert sessoes.gerar_hash(SENHA).startswith("$argon2id$")


def test_csrf_confere_so_com_o_hmac_do_token():
    csrf = sessoes.token_csrf("segredo", "token")
    assert sessoes.csrf_confere("segredo", "token", csrf)
    assert not sessoes.csrf_confere("segredo", "outro-token", csrf)
    assert not sessoes.csrf_confere("outro-segredo", "token", csrf)
    assert not sessoes.csrf_confere("segredo", "token", None)


def test_perfil_invalido_e_recusado(fabrica):
    with pytest.raises(ValueError), abrir(fabrica) as s:
        sessoes.criar_usuario(s, "x@exemplo.test", SENHA, "admin")


def test_login_certo_e_email_sem_diferenca_de_caixa(fabrica):
    usuario_id = _usuario(fabrica)
    assert _login(fabrica, email="  ANA@exemplo.test ") == usuario_id


def test_quinta_falha_bloqueia_e_derruba_sessoes(fabrica):
    _usuario(fabrica)
    with abrir(fabrica) as s:
        usuario = sessoes.autenticar(s, "ana@exemplo.test", SENHA)
        sessoes.abrir_sessao(s, usuario)

    for _ in range(sessoes.MAX_TENTATIVAS):
        assert _login(fabrica, senha="errada") is None

    # Bloqueada: nem a senha certa entra, e a sessão aberta caiu.
    assert _login(fabrica) is None
    with abrir(fabrica) as s:
        assert s.scalar(select(func.count()).select_from(SessaoPainel)) == 0


def test_bloqueio_vence_depois_de_15_minutos(fabrica, monkeypatch):
    _usuario(fabrica)
    for _ in range(sessoes.MAX_TENTATIVAS):
        _login(fabrica, senha="errada")

    depois = sessoes.agora() + sessoes.BLOQUEIO + timedelta(seconds=1)
    monkeypatch.setattr(sessoes, "agora", lambda: depois)
    assert _login(fabrica) is not None


def test_sessao_expira_em_8_horas(fabrica):
    _usuario(fabrica)
    with abrir(fabrica) as s:
        token = sessoes.abrir_sessao(s, sessoes.autenticar(s, "ana@exemplo.test", SENHA))
        assert sessoes.usuario_da_sessao(s, token) is not None
        s.execute(update(SessaoPainel).values(expira_em=func.now() - timedelta(seconds=1)))
        assert sessoes.usuario_da_sessao(s, token) is None


def test_logout_apaga_a_sessao(fabrica):
    _usuario(fabrica)
    with abrir(fabrica) as s:
        token = sessoes.abrir_sessao(s, sessoes.autenticar(s, "ana@exemplo.test", SENHA))
        sessoes.encerrar_sessao(s, token)
        assert sessoes.usuario_da_sessao(s, token) is None


def test_cli_cria_usuario(fabrica, pg_url, monkeypatch):
    monkeypatch.setenv(
        "SATURDAY_DATABASE_URL", pg_url.replace("postgresql://", "postgresql+psycopg://")
    )
    monkeypatch.setattr("getpass.getpass", lambda _prompt: SENHA)
    from saturday.settings import get_settings

    get_settings.cache_clear()
    try:
        assert criar_usuario_cli(["--email", "gestor@exemplo.test", "--perfil", "gestor"]) == 0
        assert criar_usuario_cli(["--email", "gestor@exemplo.test"]) == 1
    finally:
        get_settings.cache_clear()
    assert _login(fabrica, email="gestor@exemplo.test") is not None
