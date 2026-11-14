"""Aba Agente do painel: o grafo que roda e as execuções (turnos) de todas as conversas.

Só leitura. O grafo vem da estrutura compilada (`build_graph`), não de um desenho
à mão: o que aparece é o que roda. As execuções são os `turnos`, que guardam só
códigos, números e tempos; custo e tokens só para gestor, como na aba IA.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.graph import NOS, build_graph
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import MASCARAS
from saturday.settings import get_settings
from saturday.web.api.ia import turno_json
from saturday.web.dependencies import UsuarioLogado, exigir_fabrica, usuario_logado

router = APIRouter(prefix="/admin/agente", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]

INICIO, FIM = "__start__", "__end__"
EXTREMOS = {
    INICIO: "Entrada do turno: a mensagem do cliente ou um evento do sistema.",
    FIM: "Fim do turno: a resposta vai para o outbox.",
}
# Nó → atributo de `Settings` com o modelo que ele chama. Os demais são só código.
MODELO_DO_NO = {
    "classify_intent": "jev_model",
    "generate_answer": "llm_model",
    "read_statement": "vision_model",
}
LIMITE_EXECUCOES = 50


@cache
def _estrutura() -> tuple[list[str], list[dict[str, Any]]]:
    grafo = build_graph().get_graph()
    arestas = [
        {"de": a.source, "para": a.target, "condicional": bool(a.conditional)} for a in grafo.edges
    ]
    return list(grafo.nodes), arestas


@router.get("/grafo")
def grafo(_usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    """Nós e arestas do grafo compilado, com o modelo e as passagens das últimas 24 h."""

    nos, arestas = _estrutura()
    settings = get_settings()
    desde = datetime.now(UTC) - timedelta(hours=24)
    nos_do_caminho = (
        select(func.jsonb_array_elements_text(Turno.caminho).label("no"))
        .where(Turno.criado_em >= desde)
        .subquery()
    )
    with abrir_sessao(fabrica) as sessao:
        passagens = dict(
            sessao.execute(
                select(nos_do_caminho.c.no, func.count()).group_by(nos_do_caminho.c.no)
            ).all()
        )
        turnos_24h = sessao.scalar(select(func.count()).where(Turno.criado_em >= desde)) or 0

    def descricao(nome: str) -> str | None:
        if nome in EXTREMOS:
            return EXTREMOS[nome]
        doc = inspect.getdoc(NOS[nome]) if nome in NOS else None
        return doc.splitlines()[0] if doc else None

    def modelo(nome: str) -> dict[str, str] | None:
        atributo = MODELO_DO_NO.get(nome)
        if atributo is None:
            return None
        return {
            "variavel": f"SATURDAY_{atributo.upper()}",
            "valor": getattr(settings, atributo) or "",
        }

    return {
        "nos": [
            {
                "id": nome,
                "descricao": descricao(nome),
                "modelo": modelo(nome),
                "passagens_24h": turnos_24h if nome in EXTREMOS else passagens.get(nome, 0),
            }
            for nome in nos
        ],
        "arestas": arestas,
    }


@router.get("/execucoes")
def execucoes(
    usuario: Logado,
    fabrica: Fabrica,
    no: Annotated[str | None, Query(max_length=64)] = None,
    situacao: Annotated[Literal["todas", "erro", "handoff"], Query()] = "todas",
    antes_de: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Turnos de todas as conversas, do mais novo para o mais antigo, em páginas."""

    consulta = (
        select(Turno, Conversa.telefone, Conversa.canal)
        .join(Conversa, Conversa.id == Turno.conversa_id)
        .order_by(Turno.id.desc())
        .limit(LIMITE_EXECUCOES + 1)
    )
    if no:
        consulta = consulta.where(Turno.caminho.contains([no]))
    if situacao == "erro":
        consulta = consulta.where(Turno.erro.is_not(None))
    elif situacao == "handoff":
        consulta = consulta.where(Turno.status == "handoff")
    if antes_de is not None:
        consulta = consulta.where(Turno.id < antes_de)

    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.execute(consulta).all()

    return {
        "execucoes": [
            {
                **turno_json(turno, usuario.gestor),
                "conversa_id": str(turno.conversa_id),
                "telefone": MASCARAS["telefone"](telefone) if telefone else None,
                "canal": canal,
            }
            for turno, telefone, canal in linhas[:LIMITE_EXECUCOES]
        ],
        "tem_mais": len(linhas) > LIMITE_EXECUCOES,
    }
