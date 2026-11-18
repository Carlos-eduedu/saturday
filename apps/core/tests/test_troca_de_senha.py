"""Trocar a própria senha e troca obrigatória (decisão 0030). Exige Postgres."""

from __future__ import annotations

import re
import uuid

from conftest import SENHA_DO_PAINEL, entrar, entrar_como
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Auditoria
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import sessoes

NOVA = "outra-senha-comprida-2"  # noqa: S105 - senha de teste
ROTA = "/admin/eu/senha"
GESTAO = "/admin/gestao/usuarios"
# O que a pessoa com a troca pendente ainda alcança; o login não pede sessão.
LIVRES = {
    ("POST", "/admin/login"),
    ("GET", "/admin/eu"),
    ("POST", ROTA),
    ("POST", "/admin/logout"),
}


def _trocar(client: TestClient, cabecalhos: dict[str, str], atual: str, nova: str) -> int:
    resposta = client.post(ROTA, json={"atual": atual, "nova": nova}, headers=cabecalhos)
    return resposta.status_code


def _cadastrar(client: TestClient, fabrica: sessionmaker[Session], email: str) -> str:
    """O gestor cadastra a pessoa pela aba Usuários; devolve o id dela."""

    cabecalhos = entrar_como(client, fabrica, "gestor")
    resposta = client.post(
        GESTAO,
        json={"nome": "Ana", "email": email, "perfil": "atendente", "senha": SENHA_DO_PAINEL},
        headers=cabecalhos,
    )
    assert resposta.status_code == 201, resposta.text
    return str(resposta.json()["id"])


def test_troca_a_propria_senha_encerra_as_outras_sessoes_e_audita(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    cabecalhos = entrar_como(client_pg, fabrica, "atendente", "ana@exemplo.test")
    outro_aparelho = TestClient(client_pg.app)
    entrar(outro_aparelho, "ana@exemplo.test")

    assert _trocar(client_pg, cabecalhos, SENHA_DO_PAINEL, NOVA) == 204

    assert client_pg.get("/admin/eu").status_code == 200
    assert outro_aparelho.get("/admin/eu").status_code == 401
    recusa = outro_aparelho.post(
        "/admin/login", json={"email": "ana@exemplo.test", "senha": SENHA_DO_PAINEL}
    )
    assert recusa.status_code == 401
    entrar(outro_aparelho, "ana@exemplo.test", NOVA)
    with abrir_sessao(fabrica) as sessao:
        [linha] = sessao.scalars(
            select(Auditoria).where(Auditoria.acao == "usuario_senha_propria")
        ).all()
        assert linha.usuario_id is not None
        assert linha.alvo == str(linha.usuario_id)
        assert linha.detalhe is None


def test_senha_nova_curta_ou_igual_e_pedido_sem_csrf_sao_recusados(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    cabecalhos = entrar_como(client_pg, fabrica, "atendente", "ana@exemplo.test")

    assert _trocar(client_pg, cabecalhos, SENHA_DO_PAINEL, "curta") == 422
    assert _trocar(client_pg, cabecalhos, SENHA_DO_PAINEL, SENHA_DO_PAINEL) == 422
    assert _trocar(client_pg, {}, SENHA_DO_PAINEL, NOVA) == 403

    entrar(client_pg, "ana@exemplo.test")


def test_senha_atual_errada_nao_troca_e_a_quinta_bloqueia_e_derruba_a_sessao(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    cabecalhos = entrar_como(client_pg, fabrica, "atendente", "ana@exemplo.test")

    for _ in range(sessoes.MAX_TENTATIVAS):
        resposta = client_pg.post(
            ROTA, json={"atual": "senha-errada-123", "nova": NOVA}, headers=cabecalhos
        )
        assert resposta.status_code == 422
        assert resposta.json()["detail"] == "senha atual inválida"

    # Bloqueada como no login: a sessão caiu e nem a senha certa entra.
    assert client_pg.get("/admin/eu").status_code == 401
    for senha in (SENHA_DO_PAINEL, NOVA):
        recusa = client_pg.post("/admin/login", json={"email": "ana@exemplo.test", "senha": senha})
        assert recusa.status_code == 401


def test_acerto_zera_a_contagem_de_falhas(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    cabecalhos = entrar_como(client_pg, fabrica, "atendente", "ana@exemplo.test")
    for _ in range(sessoes.MAX_TENTATIVAS - 1):
        assert _trocar(client_pg, cabecalhos, "senha-errada-123", NOVA) == 422
    assert _trocar(client_pg, cabecalhos, SENHA_DO_PAINEL, NOVA) == 204

    assert _trocar(client_pg, cabecalhos, "senha-errada-123", SENHA_DO_PAINEL) == 422
    assert client_pg.get("/admin/eu").status_code == 200


def test_cadastrada_pelo_gestor_so_alcanca_a_troca_ate_trocar(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _cadastrar(client_pg, fabrica, "ana@exemplo.test")
    cabecalhos = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get("/admin/eu").json()["trocar_senha"] is True

    # Toda rota do /admin, inclusive as que vierem depois: recusa por padrão.
    conferidas = 0
    rotas = client_pg.app.openapi()["paths"]  # type: ignore[attr-defined]
    for rota, metodos in rotas.items():
        if not rota.startswith("/admin"):
            continue
        caminho = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), rota)
        for metodo in metodos:
            if (metodo.upper(), rota) in LIVRES:
                continue
            resposta = client_pg.request(metodo, caminho, headers=cabecalhos)
            assert resposta.status_code == 403, f"{metodo} {rota}"
            assert resposta.json()["detail"] == "troque a senha para continuar"
            conferidas += 1
    assert conferidas > 50
    assert "/admin/eventos" in rotas  # o SSE entra na recusa

    assert _trocar(client_pg, cabecalhos, SENHA_DO_PAINEL, NOVA) == 204

    assert client_pg.get("/admin/eu").json()["trocar_senha"] is False
    assert client_pg.get("/admin/conversas").status_code == 200
    # No próximo login a troca não volta.
    entrar(client_pg, "ana@exemplo.test", NOVA)
    assert client_pg.get("/admin/eu").json()["trocar_senha"] is False


def test_troca_pendente_ainda_deixa_sair(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _cadastrar(client_pg, fabrica, "ana@exemplo.test")
    cabecalhos = entrar(client_pg, "ana@exemplo.test")

    assert client_pg.post("/admin/logout", headers=cabecalhos).status_code == 204
    assert client_pg.get("/admin/eu").status_code == 401


def test_redefinida_pelo_gestor_exige_troca(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    entrar_como(client_pg, fabrica, "atendente", "ana@exemplo.test")
    assert client_pg.get("/admin/eu").json()["trocar_senha"] is False
    ana = client_pg.get("/admin/eu").json()["id"]
    cabecalhos = entrar_como(client_pg, fabrica, "gestor")

    resposta = client_pg.post(f"{GESTAO}/{ana}/senha", json={"senha": NOVA}, headers=cabecalhos)
    assert resposta.status_code == 204

    cabecalhos = entrar(client_pg, "ana@exemplo.test", NOVA)
    assert client_pg.get("/admin/eu").json()["trocar_senha"] is True
    assert client_pg.get("/admin/conversas").status_code == 403
    assert _trocar(client_pg, cabecalhos, NOVA, SENHA_DO_PAINEL) == 204
    assert client_pg.get("/admin/conversas").status_code == 200


def test_gestor_nao_redefine_a_propria_senha_pela_aba_usuarios(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    cabecalhos = entrar_como(client_pg, fabrica, "gestor", "gestora@exemplo.test")
    gestora = client_pg.get("/admin/eu").json()["id"]

    resposta = client_pg.post(f"{GESTAO}/{gestora}/senha", json={"senha": NOVA}, headers=cabecalhos)

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == (
        "você não pode redefinir a sua própria senha: troque-a em Seu perfil"
    )
    # Nada mudou: a sessão segue, sem troca pendente, e a senha é a de antes.
    assert client_pg.get("/admin/eu").json()["trocar_senha"] is False
    with abrir_sessao(fabrica) as sessao:
        assert (
            sessao.scalars(select(Auditoria).where(Auditoria.acao == "usuario_senha")).all() == []
        )
    entrar(client_pg, "gestora@exemplo.test")
