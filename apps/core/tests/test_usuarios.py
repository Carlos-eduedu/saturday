"""Aba Usuários do painel (decisão 0012). Exige Postgres."""

from __future__ import annotations

import uuid
from typing import Any

from conftest import entrar
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import Alerta, Auditoria, Conversa, SessaoPainel, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import sessoes
from saturday.painel import usuarios as regras
from saturday.painel.acoes import AcaoRecusada

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
OUTRA = "outra-senha-comprida-2"  # noqa: S105 - senha de teste
ROTA = "/admin/gestao/usuarios"


def _usuario(fabrica: sessionmaker[Session], email: str, perfil: str = "atendente") -> uuid.UUID:
    with abrir_sessao(fabrica) as sessao:
        return sessoes.criar_usuario(sessao, email, SENHA, perfil).id


def _gestor(client: TestClient, fabrica: sessionmaker[Session]) -> tuple[uuid.UUID, dict[str, str]]:
    gestor_id = _usuario(fabrica, "gestora@exemplo.test", "gestor")
    return gestor_id, entrar(client, "gestora@exemplo.test")


def _auditoria(fabrica: sessionmaker[Session], acao: str) -> list[Any]:
    with abrir_sessao(fabrica) as sessao:
        return list(sessao.scalars(select(Auditoria.detalhe).where(Auditoria.acao == acao)).all())


def test_atendente_nao_ve_a_aba(client_pg: TestClient, fabrica: sessionmaker[Session]) -> None:
    _usuario(fabrica, "ana@exemplo.test")
    cabecalhos = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get(ROTA).status_code == 403
    resposta = client_pg.post(
        ROTA,
        json={"nome": "X", "email": "x@exemplo.test", "perfil": "gestor", "senha": SENHA},
        headers=cabecalhos,
    )
    assert resposta.status_code == 403


def test_cadastra_lista_e_quem_foi_cadastrado_entra(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _, cabecalhos = _gestor(client_pg, fabrica)
    corpo = {"nome": " Ana  Souza ", "email": "Ana@Exemplo.test", "perfil": "atendente"}

    curta = client_pg.post(ROTA, json={**corpo, "senha": "curta"}, headers=cabecalhos)
    assert curta.status_code == 422
    resposta = client_pg.post(ROTA, json={**corpo, "senha": SENHA}, headers=cabecalhos)
    assert resposta.status_code == 201

    linhas = client_pg.get(ROTA).json()
    [ana] = [u for u in linhas if u["email"] == "ana@exemplo.test"]
    assert ana["nome"] == "Ana Souza"
    assert ana["situacao"] == "ativo"
    [detalhe] = _auditoria(fabrica, "usuario_criar")
    assert detalhe == {"nome": "Ana Souza", "email": "ana@exemplo.test", "perfil": "atendente"}

    repetido = client_pg.post(ROTA, json={**corpo, "senha": SENHA}, headers=cabecalhos)
    assert repetido.status_code == 409

    entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get("/admin/eu").json()["nome"] == "Ana Souza"


def test_editar_audita_so_o_que_mudou(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _, cabecalhos = _gestor(client_pg, fabrica)
    ana = _usuario(fabrica, "ana@exemplo.test")

    resposta = client_pg.patch(
        f"{ROTA}/{ana}",
        json={"nome": "Ana Lima", "email": "ana@exemplo.test", "perfil": "gestor"},
        headers=cabecalhos,
    )
    assert resposta.status_code == 204
    assert _auditoria(fabrica, "usuario_editar") == [{"nome": "Ana Lima", "perfil": "gestor"}]

    _usuario(fabrica, "bia@exemplo.test")
    conflito = client_pg.patch(
        f"{ROTA}/{ana}", json={"email": "bia@exemplo.test"}, headers=cabecalhos
    )
    assert conflito.status_code == 409


def test_redefinir_senha_derruba_sessoes_e_desbloqueia(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _, cabecalhos = _gestor(client_pg, fabrica)
    ana = _usuario(fabrica, "ana@exemplo.test")
    with abrir_sessao(fabrica) as sessao:
        usuario = sessao.get(UsuarioPainel, ana)
        assert usuario is not None
        sessoes.abrir_sessao(sessao, usuario)
        usuario.tentativas_falhas = 5
        usuario.bloqueado_ate = sessoes.agora() + sessoes.BLOQUEIO

    [linha] = [u for u in client_pg.get(ROTA).json() if u["id"] == str(ana)]
    assert linha["situacao"] == "bloqueado"

    resposta = client_pg.post(f"{ROTA}/{ana}/senha", json={"senha": OUTRA}, headers=cabecalhos)
    assert resposta.status_code == 204
    with abrir_sessao(fabrica) as sessao:
        abertas = sessao.scalars(select(SessaoPainel).where(SessaoPainel.usuario_id == ana)).all()
        assert abertas == []
    assert _auditoria(fabrica, "usuario_senha") == [None]
    entrar(client_pg, "ana@exemplo.test", OUTRA)


def test_desbloquear(client_pg: TestClient, fabrica: sessionmaker[Session]) -> None:
    _, cabecalhos = _gestor(client_pg, fabrica)
    ana = _usuario(fabrica, "ana@exemplo.test")
    with abrir_sessao(fabrica) as sessao:
        usuario = sessao.get(UsuarioPainel, ana)
        assert usuario is not None
        usuario.tentativas_falhas = 5
        usuario.bloqueado_ate = sessoes.agora() + sessoes.BLOQUEIO

    assert client_pg.post(f"{ROTA}/{ana}/desbloquear", headers=cabecalhos).status_code == 204
    entrar(client_pg, "ana@exemplo.test")


def test_desativar_devolve_conversas_derruba_sessao_e_barra_login(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    gestor_id, cabecalhos = _gestor(client_pg, fabrica)
    ana = _usuario(fabrica, "ana@exemplo.test")
    with abrir_sessao(fabrica) as sessao:
        for numero in ("1", "2"):
            conversa = repositorios.obter_ou_criar_conversa(sessao, f"chat:{numero}")
            atendimento.assumir(sessao, conversa, ana)
        usuario = sessao.get(UsuarioPainel, ana)
        assert usuario is not None
        token = sessoes.abrir_sessao(sessao, usuario)

    [linha] = [u for u in client_pg.get(ROTA).json() if u["id"] == str(ana)]
    assert linha["conversas_assumidas"] == 2

    resposta = client_pg.post(f"{ROTA}/{ana}/desativar", headers=cabecalhos)
    assert resposta.json() == {"conversas_devolvidas": 2}

    with abrir_sessao(fabrica) as sessao:
        estados = sessao.scalars(select(Conversa.atendimento)).all()
        assert sorted(estados) == ["handoff", "handoff"]
        alertas = sessao.scalars(select(Alerta.tipo)).all()
        assert alertas == ["atendente_desativado", "atendente_desativado"]
        assert sessoes.usuario_da_sessao(sessao, token) is None
    assert _auditoria(fabrica, "usuario_desativar") == [{"conversas": 2}]

    # Quem assume a conversa trata o alerta (docs/decisoes/0021).
    with abrir_sessao(fabrica) as sessao:
        conversa = repositorios.buscar_conversa(sessao, "chat:1")
        assert conversa is not None
        assert len(atendimento.assumir(sessao, conversa, gestor_id)) == 1
        abertos = sessao.scalars(select(Alerta.conversa_id).where(Alerta.resolvido_em.is_(None)))
        assert conversa.id not in abertos.all()

    # Some da lista de transferir; o login recusa como senha errada.
    destinos = client_pg.get("/admin/usuarios").json()
    assert [d["id"] for d in destinos] == [str(gestor_id)]
    recusado = client_pg.post("/admin/login", json={"email": "ana@exemplo.test", "senha": SENHA})
    assert recusado.status_code == 401

    # E-mail de desativado: recusa e manda reativar.
    novo = client_pg.post(
        ROTA,
        json={"nome": "Ana", "email": "ana@exemplo.test", "perfil": "atendente", "senha": SENHA},
        headers=entrar(client_pg, "gestora@exemplo.test"),
    )
    assert novo.status_code == 409
    assert "reative" in novo.json()["detail"]

    cabecalhos = entrar(client_pg, "gestora@exemplo.test")
    assert client_pg.post(f"{ROTA}/{ana}/reativar", headers=cabecalhos).status_code == 204
    entrar(client_pg, "ana@exemplo.test")


def test_travas_do_gestor(client_pg: TestClient, fabrica: sessionmaker[Session]) -> None:
    gestor_id, cabecalhos = _gestor(client_pg, fabrica)

    a_si = client_pg.post(f"{ROTA}/{gestor_id}/desativar", headers=cabecalhos)
    assert a_si.status_code == 409
    rebaixar = client_pg.patch(
        f"{ROTA}/{gestor_id}", json={"perfil": "atendente"}, headers=cabecalhos
    )
    assert rebaixar.status_code == 409

    # Com outro gestor, rebaixar o outro passa; aí ele não pode mais tirar o último.
    bia = _usuario(fabrica, "bia@exemplo.test", "gestor")
    ok = client_pg.patch(f"{ROTA}/{bia}", json={"perfil": "atendente"}, headers=cabecalhos)
    assert ok.status_code == 204
    with abrir_sessao(fabrica) as sessao:
        gestores = sessao.scalars(
            select(UsuarioPainel.id).where(UsuarioPainel.perfil == "gestor")
        ).all()
        assert gestores == [gestor_id]


def test_ultimo_gestor_nao_e_desativado_por_outro(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    gestor_id, _ = _gestor(client_pg, fabrica)
    bia = _usuario(fabrica, "bia@exemplo.test", "gestor")
    cabecalhos = entrar(client_pg, "bia@exemplo.test")
    assert client_pg.post(f"{ROTA}/{gestor_id}/desativar", headers=cabecalhos).status_code == 200

    # Bia agora é a única gestora ativa: ninguém mais pode desativá-la.
    with abrir_sessao(fabrica) as sessao:
        try:
            regras.desativar(sessao, gestor_id, bia)
        except AcaoRecusada as exc:
            assert exc.status == 409
        else:
            raise AssertionError("desativou o último gestor")


# ------------------------------------------------------------------ "Você"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def test_cada_um_edita_o_proprio_perfil_e_o_telefone_fica_fora_da_auditoria(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _usuario(fabrica, "ana@exemplo.test")
    csrf = entrar(client_pg, "ana@exemplo.test")

    resposta = client_pg.patch(
        "/admin/eu",
        json={"nome": "  Ana   Souza ", "telefone": "+55 (11) 98765-4321"},
        headers=csrf,
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["nome"] == "Ana Souza"
    assert resposta.json()["telefone"] == "11987654321"
    assert client_pg.get("/admin/eu").json()["telefone"] == "11987654321"
    detalhes = _auditoria(fabrica, "perfil_editar")
    assert detalhes == [{"campos": ["nome", "telefone"]}]
    assert "98765" not in str(detalhes)

    invalido = client_pg.patch("/admin/eu", json={"nome": "Ana", "telefone": "123"}, headers=csrf)
    assert invalido.status_code == 422
    # Perfil e e-mail não se trocam por aqui: são do gestor.
    assert (
        client_pg.patch(
            "/admin/eu", json={"nome": "Ana", "perfil": "gestor"}, headers=csrf
        ).status_code
        == 422
    )
    assert client_pg.patch("/admin/eu", json={"nome": "Ana"}).status_code == 403


def test_foto_do_perfil_vai_para_o_storage_e_so_logado_ve(
    client_pg: TestClient, fabrica: sessionmaker[Session], storage: Any
) -> None:
    ana = _usuario(fabrica, "ana@exemplo.test")
    csrf = entrar(client_pg, "ana@exemplo.test")

    def subir(dados: bytes, tipo: str) -> Any:
        return client_pg.put(
            "/admin/eu/foto", content=dados, headers={**csrf, "Content-Type": tipo}
        )

    assert subir(b"GIF89a", "image/gif").status_code == 415
    assert subir(b"nao e png", "image/png").status_code == 415
    assert (
        subir(b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024), "image/png").status_code == 413
    )

    primeira = subir(PNG, "image/png").json()["foto"]
    assert primeira.startswith(f"/admin/usuarios/{ana}/foto?v=")
    assert client_pg.get(primeira).content == PNG
    segunda = subir(JPG, "image/jpeg").json()["foto"]
    assert segunda != primeira
    resposta = client_pg.get(segunda)
    assert resposta.content == JPG and resposta.headers["content-type"] == "image/jpeg"
    # A anterior sai do storage: só a atual fica.
    assert len([k for k in storage._objetos if k.startswith("painel/usuarios/")]) == 1

    # A equipe vê a foto e o telefone mascarado na lista.
    _gestor(client_pg, fabrica)
    linha = next(u for u in client_pg.get(ROTA).json() if u["id"] == str(ana))
    assert linha["foto"] == segunda

    client_pg.cookies.clear()
    assert client_pg.get(segunda).status_code == 401

    entrar(client_pg, "ana@exemplo.test")
    csrf = {"X-CSRF-Token": client_pg.get("/admin/eu").json()["csrf"]}
    assert client_pg.delete("/admin/eu/foto", headers=csrf).json()["foto"] is None
    assert not [k for k in storage._objetos if k.startswith("painel/usuarios/")]
    assert client_pg.get(segunda).status_code == 404
    assert _auditoria(fabrica, "perfil_foto_remover")


def test_gestor_liga_e_desliga_dados_sem_mascara_com_auditoria(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    gestor_id, cabecalhos = _gestor(client_pg, fabrica)
    ana = _usuario(fabrica, "ana@exemplo.test")

    for valor in (True, False):
        resposta = client_pg.patch(
            f"{ROTA}/{ana}", json={"ve_dados_completos": valor}, headers=cabecalhos
        )
        assert resposta.status_code == 204
    assert _auditoria(fabrica, "usuario_editar") == [
        {"ve_dados_completos": True},
        {"ve_dados_completos": False},
    ]
    # O gestor liga também para si mesmo (decisão 0037).
    proprio = client_pg.patch(
        f"{ROTA}/{gestor_id}", json={"ve_dados_completos": True}, headers=cabecalhos
    )
    assert proprio.status_code == 204
    assert client_pg.get("/admin/eu").json()["ve_dados_completos"] is True

    atendente = entrar(client_pg, "ana@exemplo.test")
    recusa = client_pg.patch(f"{ROTA}/{ana}", json={"ve_dados_completos": True}, headers=atendente)
    assert recusa.status_code == 403
    assert client_pg.get("/admin/eu").json()["ve_dados_completos"] is False
