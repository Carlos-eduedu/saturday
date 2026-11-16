"""Cada verbo de `dados/atendimento.py` e os alertas dele (decisões 0018 e 0021).

Exige Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import Alerta, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao

TODOS = ("handoff", "erro_interno", "atendente_desativado", "sem_resposta", "evento_com_humano")


def _cenario(sessao, conversation_id):
    """Conversa com um alerta aberto de cada tipo e dois atendentes."""

    conversa = repositorios.obter_ou_criar_conversa(sessao, conversation_id)
    pessoas = []
    for email in ("ana@exemplo.test", "bia@exemplo.test"):
        pessoa = UsuarioPainel(email=email, nome=email, senha_hash="x", perfil="atendente")
        sessao.add(pessoa)
        pessoas.append(pessoa)
    sessao.flush()
    for tipo in TODOS:
        repositorios.abrir_alerta(sessao, tipo, conversa_id=conversa.id)
    return conversa, pessoas[0].id, pessoas[1].id


def _abertos(sessao):
    return set(sessao.scalars(select(Alerta.tipo).where(Alerta.resolvido_em.is_(None))))


@pytest.mark.parametrize(
    ("verbo", "estado", "com_dono", "ficam_abertos"),
    [
        ("assumir", "assumida", True, {"sem_resposta", "evento_com_humano"}),
        ("devolver", "ia", False, {"evento_com_humano"}),
        ("devolver_sozinha", "ia", False, {"evento_com_humano"}),
        ("transferir", "assumida", True, set(TODOS)),
        ("restaurar", "handoff", False, set(TODOS)),
    ],
)
def test_verbo_muda_o_estado_e_resolve_so_os_alertas_dele(
    fabrica, conversa, verbo, estado, com_dono, ficam_abertos
):
    with abrir_sessao(fabrica) as sessao:
        linha, ana, bia = _cenario(sessao, conversa)
        resolvidos: list[int] = []
        por = ana
        if verbo == "assumir":
            resolvidos = atendimento.assumir(sessao, linha, ana)
        elif verbo == "devolver":
            resolvidos = atendimento.devolver(sessao, linha, ana)
        elif verbo == "devolver_sozinha":
            por = None
            resolvidos = atendimento.devolver(sessao, linha, None)
        elif verbo == "transferir":
            atendimento.transferir(sessao, linha, ana)
        else:
            atendimento.restaurar(sessao, linha, "handoff", bia)

        assert linha.atendimento == estado
        # Dono só existe em conversa assumida, mesmo que alguém passe um.
        assert linha.atendente_id == (ana if com_dono else None)
        assert _abertos(sessao) == ficam_abertos
        autores = sessao.scalars(select(Alerta.resolvido_por).where(Alerta.id.in_(resolvidos)))
        assert len(resolvidos) == len(TODOS) - len(ficam_abertos)
        assert set(autores) <= {por}


def test_entrar_em_handoff_abre_o_alerta_uma_vez_so(fabrica, conversa):
    with abrir_sessao(fabrica) as sessao:
        linha = repositorios.obter_ou_criar_conversa(sessao, conversa)
        primeiro = atendimento.entrar_em_handoff(sessao, linha, "handoff", {"motivo": "humano"})
        segundo = atendimento.entrar_em_handoff(sessao, linha, "handoff", {"motivo": "outro"})

        assert linha.atendimento == "handoff"
        assert segundo.id == primeiro.id
        assert sessao.scalars(select(Alerta.tipo)).all() == ["handoff"]
