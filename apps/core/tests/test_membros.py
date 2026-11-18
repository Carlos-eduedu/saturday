"""Aba Membros: quem vê o quê, estado, atividade e disponibilidade (decisão 0023)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from conftest import SENHA_DO_PAINEL, entrar
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Auditoria, Conversa, Mensagem, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import membros, sessoes

SO_DO_GESTOR = {"situacao", "bloqueado_ate", "tentativas_falhas", "observacao", "trocar_senha"}
DE_QUEM_PODE = {"email", "telefone", "ultimo_acesso_em", "criado_em", "pode_editar_agente"}


def _usuario(fabrica: sessionmaker[Session], email: str, perfil: str = "atendente") -> uuid.UUID:
    with abrir_sessao(fabrica) as sessao:
        return sessoes.criar_usuario(sessao, email, SENHA_DO_PAINEL, perfil).id


def test_estado_do_membro() -> None:
    agora = sessoes.agora()
    pessoa = UsuarioPainel(disponivel=True, ultimo_acesso_em=None)
    assert membros.estado(pessoa, agora) == "fora"
    pessoa.ultimo_acesso_em = agora - timedelta(minutes=4, seconds=59)
    assert membros.estado(pessoa, agora) == "disponivel"
    pessoa.ultimo_acesso_em = agora - timedelta(minutes=5)
    assert membros.estado(pessoa, agora) == "fora"
    # Ausente vence: a pessoa marcou, mesmo estando no painel.
    pessoa.disponivel = False
    pessoa.ultimo_acesso_em = agora
    assert membros.estado(pessoa, agora) == "ausente"


def test_acesso_e_regravado_no_maximo_uma_vez_por_minuto() -> None:
    agora = sessoes.agora()
    pessoa = UsuarioPainel(ultimo_acesso_em=None)
    membros.marcar_acesso(pessoa, agora)
    assert pessoa.ultimo_acesso_em == agora
    membros.marcar_acesso(pessoa, agora + timedelta(seconds=59))
    assert pessoa.ultimo_acesso_em == agora
    membros.marcar_acesso(pessoa, agora + timedelta(seconds=60))
    assert pessoa.ultimo_acesso_em == agora + timedelta(seconds=60)


def test_colega_ve_so_o_que_serve_para_transferir(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    bia = _usuario(fabrica, "bia@exemplo.test")
    _usuario(fabrica, "ana@exemplo.test")
    entrar(client_pg, "ana@exemplo.test")

    lista = {m["nome"]: m for m in client_pg.get("/admin/membros").json()}
    assert set(lista) == {"ana", "bia"}
    colega = lista["bia"]
    assert colega["nivel"] == "colega" and colega["voce"] is False
    assert colega["estado"] == "fora" and colega["conversas_assumidas"] == 0
    assert not (SO_DO_GESTOR | DE_QUEM_PODE) & set(colega)

    detalhe = client_pg.get(f"/admin/membros/{bia}").json()
    assert "atividade" not in detalhe and "acoes" not in detalhe
    assert not (SO_DO_GESTOR | DE_QUEM_PODE) & set(detalhe)


def test_a_propria_pessoa_ve_contato_acesso_e_atividade(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    ana = _usuario(fabrica, "ana@exemplo.test")
    entrar(client_pg, "ana@exemplo.test")

    eu = client_pg.get(f"/admin/membros/{ana}").json()
    assert eu["nivel"] == "proprio" and eu["voce"] is True
    assert eu["email"] == "ana@exemplo.test"
    # Entrar e pedir a página já é uso do painel.
    assert eu["estado"] == "disponivel" and eu["ultimo_acesso_em"]
    assert eu["atividade"] == {"mensagens": 0, "assumidas": 0, "devolvidas": 0, "transferidas": 0}
    assert not SO_DO_GESTOR & set(eu)


def test_gestor_ve_tudo_inclusive_desativados(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    bia = _usuario(fabrica, "bia@exemplo.test")
    _usuario(fabrica, "ana@exemplo.test")
    _usuario(fabrica, "gestora@exemplo.test", "gestor")
    csrf = entrar(client_pg, "gestora@exemplo.test")
    edicao = client_pg.patch(
        f"/admin/gestao/usuarios/{bia}",
        json={"cargo": "  Atendente   CLT ", "observacao": "em treinamento"},
        headers=csrf,
    )
    assert edicao.status_code == 204
    client_pg.post(f"/admin/gestao/usuarios/{bia}/desativar", headers=csrf)

    detalhe = client_pg.get(f"/admin/membros/{bia}").json()
    assert detalhe["nivel"] == "gestor" and detalhe["situacao"] == "desativado"
    assert detalhe["cargo"] == "Atendente CLT" and detalhe["observacao"] == "em treinamento"
    assert detalhe["tentativas_falhas"] == 0 and "atividade" in detalhe
    assert len(client_pg.get("/admin/membros").json()) == 3

    # A auditoria guarda que a observação mudou, nunca o texto.
    with abrir_sessao(fabrica) as sessao:
        mudancas = sessao.scalar(
            select(Auditoria.detalhe).where(Auditoria.acao == "usuario_editar")
        )
    assert mudancas == {"cargo": "Atendente CLT", "observacao": "alterada"}

    # Para o atendente, o desativado não existe.
    entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get(f"/admin/membros/{bia}").status_code == 404
    assert {m["nome"] for m in client_pg.get("/admin/membros").json()} == {"ana", "gestora"}


def test_troca_de_senha_pendente_aparece_so_para_o_gestor(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    bia = _usuario(fabrica, "bia@exemplo.test")
    ana = _usuario(fabrica, "ana@exemplo.test")
    _usuario(fabrica, "gestora@exemplo.test", "gestor")
    with abrir_sessao(fabrica) as sessao:
        pendente = sessao.get(UsuarioPainel, bia)
        assert pendente is not None
        pendente.trocar_senha = True

    entrar(client_pg, "gestora@exemplo.test")
    lista = {m["nome"]: m for m in client_pg.get("/admin/membros").json()}
    assert lista["bia"]["trocar_senha"] is True
    assert lista["ana"]["trocar_senha"] is False
    assert client_pg.get(f"/admin/membros/{bia}").json()["trocar_senha"] is True

    # O atendente não recebe o campo, nem como falso: nem o do colega, nem o próprio.
    entrar(client_pg, "ana@exemplo.test")
    assert all("trocar_senha" not in m for m in client_pg.get("/admin/membros").json())
    assert "trocar_senha" not in client_pg.get(f"/admin/membros/{bia}").json()
    assert "trocar_senha" not in client_pg.get(f"/admin/membros/{ana}").json()


def test_funcao_longa_demais_e_recusada(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    bia = _usuario(fabrica, "bia@exemplo.test")
    _usuario(fabrica, "gestora@exemplo.test", "gestor")
    csrf = entrar(client_pg, "gestora@exemplo.test")
    resposta = client_pg.patch(
        f"/admin/gestao/usuarios/{bia}", json={"cargo": "x" * 61}, headers=csrf
    )
    assert resposta.status_code == 422


def test_atividade_conta_sete_dias_e_as_acoes_nao_levam_detalhe(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    ana = _usuario(fabrica, "ana@exemplo.test")
    agora = sessoes.agora()
    velha = agora - timedelta(days=8)
    with abrir_sessao(fabrica) as sessao:
        conversa = Conversa(conversation_id="membros-1", canal="whatsapp")
        sessao.add(conversa)
        sessao.flush()
        conversa_id = conversa.id
        for acao, quando in [("assumir", agora), ("assumir", velha), ("devolver", agora)]:
            sessao.add(
                Auditoria(
                    usuario_id=ana,
                    acao=acao,
                    alvo=str(conversa_id),
                    detalhe={"segredo": "x"},
                    criada_em=quando,
                )
            )
        sessao.add(Auditoria(usuario_id=ana, acao="usuario_senha", alvo=str(ana), criada_em=agora))
        for quando in (agora, velha):
            sessao.add(
                Mensagem(
                    conversa_id=conversa_id,
                    direcao="saida",
                    autor="atendente",
                    usuario_id=ana,
                    conteudo="oi",
                    criada_em=quando,
                )
            )
    entrar(client_pg, "ana@exemplo.test")

    eu = client_pg.get(f"/admin/membros/{ana}").json()
    assert eu["atividade"] == {"mensagens": 1, "assumidas": 1, "devolvidas": 1, "transferidas": 0}
    assert all(set(a) == {"acao", "quando", "conversa_id"} for a in eu["acoes"])
    por_acao = {a["acao"]: a["conversa_id"] for a in eu["acoes"]}
    assert por_acao["assumir"] == str(conversa_id)
    # Ação que não é de conversa não vira link.
    assert por_acao["usuario_senha"] is None


def test_ausente_aparece_para_quem_transfere(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    _usuario(fabrica, "bia@exemplo.test")
    _usuario(fabrica, "ana@exemplo.test")
    csrf = entrar(client_pg, "bia@exemplo.test")
    sem_csrf = client_pg.patch("/admin/eu/disponibilidade", json={"disponivel": False})
    assert sem_csrf.status_code == 403
    resposta = client_pg.patch(
        "/admin/eu/disponibilidade", json={"disponivel": False}, headers=csrf
    )
    assert resposta.status_code == 200 and resposta.json()["disponivel"] is False
    assert client_pg.get("/admin/eu").json()["disponivel"] is False

    entrar(client_pg, "ana@exemplo.test")
    destinos = {u["nome"]: u["estado"] for u in client_pg.get("/admin/usuarios").json()}
    assert destinos == {"ana": "disponivel", "bia": "ausente"}
