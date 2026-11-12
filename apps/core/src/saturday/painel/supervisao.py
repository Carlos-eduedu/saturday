"""O que a lista do painel mostra para a equipe supervisionar a IA.

Para cada conversa: a última fala (autor e prévia), a etapa, o motivo do
handoff, desde quando o cliente espera resposta e se o último envio falhou.
Com isso, decide quem pede atenção e em que ordem a lista aparece. Tudo sai de
três consultas para a página inteira, sem ler checkpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from saturday.dados.modelos import Alerta, Conversa, Mensagem

# Cliente sem resposta por mais que isto pede atenção.
ESPERA_ATENCAO = timedelta(minutes=5)
# Etapas em que a IA fala de dinheiro com o cliente.
ETAPAS_DE_DINHEIRO = frozenset({"oferta", "aceite", "proposta"})
PREVIA_MAXIMA = 140
TIPOS_DE_HANDOFF = ("handoff", "erro_interno")


def _previa(mensagem: Mensagem) -> str:
    texto = " ".join(mensagem.conteudo.split())
    if not texto and mensagem.anexos:
        mime = str(mensagem.anexos[0].get("mime_type") or "")
        if mime.startswith("image/"):
            return "[Foto]"
        if mime.startswith("audio/"):
            return "[Áudio]"
        return "[Documento]"
    if len(texto) > PREVIA_MAXIMA:
        return texto[: PREVIA_MAXIMA - 1].rstrip() + "…"
    return texto


def _ultimas(
    sessao: Session, ids: list[uuid.UUID], direcao: str | None
) -> dict[uuid.UUID, Mensagem]:
    """Última mensagem de cada conversa (de uma direção, se pedida)."""

    consulta = select(Mensagem).where(Mensagem.conversa_id.in_(ids))
    if direcao is not None:
        consulta = consulta.where(Mensagem.direcao == direcao)
    consulta = consulta.order_by(
        Mensagem.conversa_id, Mensagem.criada_em.desc(), Mensagem.id.desc()
    ).ext(distinct_on(Mensagem.conversa_id))
    return {m.conversa_id: m for m in sessao.scalars(consulta)}


def _motivos_de_handoff(sessao: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    consulta = (
        select(Alerta)
        .where(Alerta.conversa_id.in_(ids), Alerta.tipo.in_(TIPOS_DE_HANDOFF))
        .order_by(Alerta.conversa_id, Alerta.criado_em.desc(), Alerta.id.desc())
        .ext(distinct_on(Alerta.conversa_id))
    )
    motivos: dict[uuid.UUID, str] = {}
    for alerta in sessao.scalars(consulta):
        motivo = (alerta.detalhe or {}).get("motivo") or alerta.tipo
        if alerta.conversa_id is not None:
            motivos[alerta.conversa_id] = str(motivo)
    return motivos


def supervisao(
    sessao: Session, conversas: list[Conversa], agora: datetime
) -> dict[uuid.UUID, dict[str, Any]]:
    """Campos de supervisão por conversa, com `atencao` (motivos) calculada."""

    ids = [c.id for c in conversas]
    if not ids:
        return {}
    ultima = _ultimas(sessao, ids, None)
    ultima_saida = _ultimas(sessao, ids, "saida")
    motivos = _motivos_de_handoff(sessao, ids)

    resultado: dict[uuid.UUID, dict[str, Any]] = {}
    for conversa in conversas:
        fala = ultima.get(conversa.id)
        saida = ultima_saida.get(conversa.id)
        # O cliente espera quando a última mensagem é dele.
        aguardando = fala.criada_em if fala is not None and fala.direcao == "entrada" else None
        falhou = saida is not None and saida.status_entrega == "failed"
        motivo = motivos.get(conversa.id) if conversa.atendimento == "handoff" else None

        atencao: list[str] = []
        if aguardando is not None and agora - aguardando > ESPERA_ATENCAO:
            atencao.append("sem_resposta")
        if conversa.atendimento == "handoff":
            atencao.append("handoff")
        if conversa.etapa in ETAPAS_DE_DINHEIRO:
            atencao.append("dinheiro")
        if falhou:
            atencao.append("envio_falhou")

        resultado[conversa.id] = {
            "ultima_mensagem": (
                {"autor": fala.autor, "texto": _previa(fala), "em": fala.criada_em}
                if fala is not None
                else None
            ),
            "etapa": conversa.etapa,
            "motivo_handoff": motivo,
            "aguardando_desde": aguardando,
            "envio_falhou": falhou,
            "atencao": atencao,
        }
    return resultado


def ordenar(resumos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quem pede atenção primeiro, pela maior espera; depois a atividade mais recente."""

    def chave(r: dict[str, Any]) -> tuple[int, float]:
        if r["atencao"]:
            desde = r["aguardando_desde"] or r["ultima_atividade"]
            return (0, desde.timestamp() if desde else 0.0)
        atividade = r["ultima_atividade"]
        return (1, -atividade.timestamp() if atividade else 0.0)

    return sorted(resumos, key=chave)
