"""Funil da aba Operação: conversas por etapa da jornada e por produto.

O que cada célula mede, de onde sai e por que o período é a coorte da conversa
iniciada estão na decisão 0031. Tudo sai de tabelas, numa consulta agregada:
nada do estado do grafo, e nenhuma conta no painel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Select, and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import InstrumentedAttribute, Session

from saturday.agent.clt.nos import CONSENTIMENTO_CONSULTA
from saturday.agent.clt.proposta import CONSENTIMENTO_PROPOSTA
from saturday.agent.coleta import hoje_operacao
from saturday.agent.nodes import CONSENTIMENTO_SIMULACAO_C6
from saturday.agent.service import RAMO_DA_OFERTA
from saturday.dados import repositorios
from saturday.dados.modelos import Consentimento, Conversa, Mensagem, PropostaGranatech, Turno
from saturday.settings import TZ_OPERACAO

Periodo = Literal["hoje", "7d", "30d", "mes"]

# Os ids dos produtos são os ramos de `RAMO_DA_OFERTA`.
PRODUTOS = (
    ("clt", "Crédito do Trabalhador (CLT)"),
    ("portabilidade", "Portabilidade INSS (C6)"),
    ("contrato_novo", "Contrato novo INSS (C6)"),
    ("icred", "iCred (INSS)"),
)
ETAPAS = (
    ("iniciadas", "Conversas iniciadas"),
    ("sim", "SIM dado"),
    ("oferta", "Oferta apresentada"),
    ("aceite", "Aceite"),
    ("proposta", "Proposta criada"),
    ("pago", "Pago"),
)
# A conversa começa num público, não num produto: as três ofertas do INSS
# partem das mesmas conversas.
PUBLICO = {"clt": "clt", "portabilidade": "inss", "contrato_novo": "inss", "icred": "inss"}
# Etapa que o produto não tem hoje: a portabilidade sai do extrato, sem pedido
# de SIM; no C6 e no iCred o aceite vai para o atendente, que digita no banco.
NAO_SE_APLICA = frozenset(
    {("sim", "portabilidade")}
    | {(e, p) for e in ("proposta", "pago") for p in ("portabilidade", "contrato_novo", "icred")}
)
SIM = {
    CONSENTIMENTO_CONSULTA: "clt",
    CONSENTIMENTO_SIMULACAO_C6: "contrato_novo",
    "icred_consulta": "icred",
}
ACEITE_COM_PROVA = {CONSENTIMENTO_PROPOSTA: "clt", "icred_aceite": "icred"}
# Motivo do handoff no turno em que o cliente aceitou a oferta. No CLT, com a
# proposta automática desligada o aceite vai a um especialista (`aceite_clt`);
# ligada, segue para os dados da proposta ou para em `dados_divergentes`.
ETAPA_DEPOIS_DO_ACEITE_CLT = "dados_proposta"
ACEITE_COM_HANDOFF = {
    "aceite_clt": "clt",
    "dados_divergentes": "clt",
    "aceitou_contrato_novo": "contrato_novo",
    "aceitou_portabilidade": "portabilidade",
}


def _inicio(periodo: Periodo, hoje: date) -> date:
    if periodo == "mes":
        return hoje.replace(day=1)
    return hoje - timedelta(days={"hoje": 0, "7d": 6, "30d": 29}[periodo])


def _marco(
    conversa: InstrumentedAttribute[Any], etapa: str, produto: Any, *onde: ColumnElement[bool]
) -> Select[tuple[uuid.UUID, str, str]]:
    return select(
        conversa.label("conversa"), literal(etapa).label("etapa"), produto.label("produto")
    ).where(*onde)


def _taxa(conversas: int, anterior: int | None) -> int | None:
    """Porcentagem inteira, com a metade para cima (o `round` do Python iria ao par)."""

    return (200 * conversas + anterior) // (2 * anterior) if anterior else None


def _marcos() -> list[Select[tuple[uuid.UUID, str, str]]]:
    """Uma linha por (conversa, etapa, produto) que o banco registra, sem filtro de período."""

    publico = Turno.classificacao["publico"].astext
    do_clt = or_(publico == "clt", and_(Turno.etapa.is_not(None), Turno.etapa != "inss"))
    do_inss = or_(publico == "inss", Turno.etapa == "inss")
    com_publico = (
        select(Turno.id).where(Turno.conversa_id == Conversa.id, or_(do_clt, do_inss)).exists()
    )
    # A chave junta falas com `+`; a parte inteira é que vale (`oferta` não é
    # `oferta_sem_seguro`).
    chave = func.concat("+", Mensagem.chave_mensagem, "+")
    ramo = case(
        *[
            (chave.contains(f"+{parte}+", autoescape=True), do_ramo)
            for parte, do_ramo in RAMO_DA_OFERTA.items()
        ]
    )
    de_verdade = PropostaGranatech.teste.is_(False)
    return [
        _marco(Conversa.id, "iniciadas", literal("todas")),
        _marco(Conversa.id, "iniciadas", literal("sem_publico"), ~com_publico),
        _marco(Turno.conversa_id, "iniciadas", literal("clt"), do_clt),
        _marco(Turno.conversa_id, "iniciadas", literal("inss"), do_inss),
        _marco(
            Consentimento.conversa_id,
            "sim",
            case(SIM, value=Consentimento.tipo),
            Consentimento.tipo.in_(SIM),
        ),
        _marco(
            Mensagem.conversa_id,
            "oferta",
            ramo,
            Mensagem.direcao == "saida",
            ramo.is_not(None),
        ),
        _marco(
            Consentimento.conversa_id,
            "aceite",
            case(ACEITE_COM_PROVA, value=Consentimento.tipo),
            Consentimento.tipo.in_(ACEITE_COM_PROVA),
        ),
        _marco(
            Turno.conversa_id,
            "aceite",
            case(ACEITE_COM_HANDOFF, value=Turno.motivo),
            Turno.motivo.in_(ACEITE_COM_HANDOFF),
        ),
        _marco(
            Turno.conversa_id,
            "aceite",
            literal("clt"),
            Turno.etapa == ETAPA_DEPOIS_DO_ACEITE_CLT,
        ),
        _marco(
            PropostaGranatech.conversa_id,
            "proposta",
            literal("clt"),
            de_verdade,
            PropostaGranatech.estado_envio == "criada",
        ),
        _marco(
            PropostaGranatech.conversa_id,
            "pago",
            literal("clt"),
            de_verdade,
            PropostaGranatech.status == "PAYED",
        ),
    ]


def funil(sessao: Session, periodo: Periodo) -> dict[str, Any]:
    """Etapa × produto das conversas iniciadas no período, com a taxa de passagem.

    Coorte: a conversa entra pelo dia em que começou (fuso da operação) e leva
    junto as etapas que alcançou depois, em qualquer data. Conversa de membro
    testador fica fora, como nos custos (decisão 0020).
    """

    fuso = ZoneInfo(TZ_OPERACAO)
    hoje = hoje_operacao()
    de = _inicio(periodo, hoje)
    inicio = datetime.combine(de, datetime.min.time(), fuso).astimezone(UTC)
    fim = datetime.combine(hoje + timedelta(days=1), datetime.min.time(), fuso).astimezone(UTC)

    coorte = (
        select(Conversa.id)
        .where(
            Conversa.criada_em >= inicio,
            Conversa.criada_em < fim,
            or_(
                Conversa.telefone.is_(None),
                Conversa.telefone.not_in(list(repositorios.testadores(sessao))),
            ),
        )
        .cte("coorte")
    )
    # O filtro da coorte entra em cada ramo da união, para cada tabela ser lida
    # pelo índice da conversa e não inteira.
    marcos = union_all(
        *[m.where(m.selected_columns.conversa.in_(select(coorte.c.id))) for m in _marcos()]
    ).subquery()
    contagens = {
        (etapa, produto): int(conversas)
        for etapa, produto, conversas in sessao.execute(
            select(
                marcos.c.etapa, marcos.c.produto, func.count(marcos.c.conversa.distinct())
            ).group_by(marcos.c.etapa, marcos.c.produto)
        )
    }

    def conversas(etapa: str, produto: str) -> int:
        chave = PUBLICO[produto] if etapa == "iniciadas" else produto
        return contagens.get((etapa, chave), 0)

    produtos = []
    for produto, nome in PRODUTOS:
        celulas: list[dict[str, int | None] | None] = []
        anterior: int | None = None
        for etapa, _rotulo in ETAPAS:
            if (etapa, produto) in NAO_SE_APLICA:
                celulas.append(None)
                continue
            n = conversas(etapa, produto)
            # A taxa é sobre a etapa anterior que o produto tem.
            celulas.append({"conversas": n, "taxa": _taxa(n, anterior)})
            anterior = n
        produtos.append({"id": produto, "nome": nome, "celulas": celulas})
    return {
        "periodo": periodo,
        "de": de,
        "ate": hoje,
        "iniciadas": contagens.get(("iniciadas", "todas"), 0),
        "sem_publico": contagens.get(("iniciadas", "sem_publico"), 0),
        "etapas": [{"id": etapa, "rotulo": rotulo} for etapa, rotulo in ETAPAS],
        # Uma célula por etapa, na ordem de `etapas`; nula quando não se aplica.
        "produtos": produtos,
    }
