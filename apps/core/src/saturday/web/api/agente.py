"""Aba Agente do painel: o grafo que roda e as execuções (turnos) de todas as conversas.

Só leitura. O grafo vem da estrutura compilada (`build_graph`), não de um desenho
à mão: o que aparece é o que roda. As execuções são os `turnos`, que guardam só
códigos, números e tempos; custo e tokens só para gestor, como na aba IA. O
estado de cada nó de uma execução vem dos checkpoints do LangGraph, filtrado aos
campos técnicos: nenhum texto do cliente nem dado pessoal sai daqui.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.graph import NOS, build_graph
from saturday.agent.service import AgentService
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import exibir
from saturday.settings import get_settings
from saturday.web.api.ia import turno_json
from saturday.web.dependencies import (
    UsuarioLogado,
    get_agent_service,
    get_fabrica,
    usuario_logado,
)

router = APIRouter(prefix="/admin/agente", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
Servico = Annotated[AgentService, Depends(get_agent_service)]

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
# Campos do estado que o painel pode ver por nó: códigos, contadores e flags.
# Texto do cliente ou do modelo e dados pessoais (`cliente`, `hiscon`, o resto de
# `clt`...) ficam de fora; quando mudam, só o nome aparece.
CAMPOS_TECNICOS = (
    "status",
    "intent",
    "intent_confidence",
    "publico",
    "needs_human",
    "handoff_reason",
    "aguardando",
    "tentativas_coleta",
    "tentativas_extrato",
    "tentativas_resposta",
    "oferta_pendente",
    "evento_sistema",
    "chave_mensagem",
    "modelo_aviso",
    "modelo_envio",
    "clt_faq",
    "marketing",
)
CAMPOS_TECNICOS_CLT = ("etapa", "passo", "motivo", "erros", "novas_simulacoes", "falhas_pagamento")
# Até onde voltar no histórico da conversa antes do horário do turno.
FOLGA_HISTORICO = timedelta(minutes=5)


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
        passagens: dict[str, int] = dict(
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
        membros = repositorios.testadores(sessao)

    return {
        "execucoes": [
            {
                **turno_json(turno, usuario.gestor),
                "conversa_id": str(turno.conversa_id),
                "telefone": exibir("telefone", telefone, usuario.ve_dados_completos)
                if telefone
                else None,
                "canal": canal,
                "membro": membros.get(telefone) if telefone else None,
            }
            for turno, telefone, canal in linhas[:LIMITE_EXECUCOES]
        ],
        "tem_mais": len(linhas) > LIMITE_EXECUCOES,
    }


@router.get("/execucoes/{turno_id}/passos")
def passos(turno_id: int, _usuario: Logado, fabrica: Fabrica, servico: Servico) -> dict[str, Any]:
    """O estado técnico depois de cada nó de uma execução, lido dos checkpoints.

    ``passos`` vem nulo quando os checkpoints do turno já não existem (a retenção
    poda a conversa) ou quando nenhum trecho do histórico bate com o caminho.
    """

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.execute(
            select(Turno, Conversa.conversation_id)
            .join(Conversa, Conversa.id == Turno.conversa_id)
            .where(Turno.id == turno_id)
        ).first()
    if linha is None:
        raise HTTPException(status_code=404, detail="execução não encontrada")
    turno, thread_id = linha
    historico = servico.graph.get_state_history(servico.config(thread_id))
    return {"passos": passos_do_turno(historico, turno.caminho, turno.criado_em)}


def passos_do_turno(
    historico: Iterable[Any], caminho: list[str], criado_em: datetime
) -> list[dict[str, Any]] | None:
    """Acha no histórico (do mais novo ao mais antigo) o trecho do turno.

    Cada execução do grafo começa num checkpoint ``input``; o checkpoint que vem
    depois de um com ``next == (nó,)`` é o estado depois daquele nó. O turno não
    guarda o id do checkpoint: vale o trecho com o mesmo caminho cujo início está
    mais perto do horário do turno.
    """

    if not caminho:
        return None
    limite = criado_em - FOLGA_HISTORICO
    lidos: list[Any] = []
    for snapshot in historico:
        lidos.append(snapshot)
        if snapshot.metadata.get("source") == "input" and _quando(snapshot) < limite:
            break
    lidos.reverse()

    trechos: list[tuple[datetime, list[dict[str, Any]]]] = []
    for anterior, atual in zip(lidos, lidos[1:], strict=False):
        if anterior.metadata.get("source") == "input":
            trechos.append((_quando(anterior), []))
        no = anterior.next[0] if len(anterior.next) == 1 else None
        if trechos and no and not no.startswith("__") and atual.metadata.get("source") == "loop":
            trechos[-1][1].append(_passo(no, anterior.values or {}, atual.values or {}))

    candidatos = [
        (abs(inicio - criado_em), p) for inicio, p in trechos if [x["no"] for x in p] == caminho
    ]
    return min(candidatos, key=lambda c: c[0])[1] if candidatos else None


def _quando(snapshot: Any) -> datetime:
    return datetime.fromisoformat(snapshot.created_at)


def _passo(no: str, antes: dict[str, Any], depois: dict[str, Any]) -> dict[str, Any]:
    clt_antes, clt_depois = antes.get("clt") or {}, depois.get("clt") or {}
    campos = [(c, antes.get(c), depois.get(c)) for c in CAMPOS_TECNICOS]
    campos += [(f"clt.{c}", clt_antes.get(c), clt_depois.get(c)) for c in CAMPOS_TECNICOS_CLT]
    visiveis = set(CAMPOS_TECNICOS) | {"clt"}
    ocultos = sorted(
        c
        for c in antes.keys() | depois.keys()
        if c not in visiveis and antes.get(c) != depois.get(c)
    )
    ocultos += sorted(
        f"clt.{c}"
        for c in clt_antes.keys() | clt_depois.keys()
        if c not in CAMPOS_TECNICOS_CLT and clt_antes.get(c) != clt_depois.get(c)
    )
    return {
        "no": no,
        "campos": [
            {"campo": c, "valor": _escalar(d), "mudou": a != d}
            for c, a, d in campos
            if a is not None or d is not None
        ],
        "ocultos": ocultos,
    }


def _escalar(valor: Any) -> str | int | float | bool | None:
    # Os campos técnicos são escalares; qualquer outra coisa vira só o tipo.
    return (
        valor
        if valor is None or isinstance(valor, str | int | float | bool)
        else type(valor).__name__
    )
