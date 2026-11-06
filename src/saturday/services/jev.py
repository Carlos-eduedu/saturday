"""Classificação de intenção pelo Jev, via OpenRouter Decisions API.

Este é o único módulo que fala com o Jev. Os nós recebem o resultado já
normalizado e nunca montam requisições HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from saturday.config import JEV_TIMEOUT_S, get_settings
from saturday.services import openrouter

logger = logging.getLogger(__name__)

OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

INTENTS = ("duvida", "suporte", "humano")
PUBLICOS = ("clt", "inss", "servidor_publico", "autonomo", "indefinido")
RESPOSTAS_OFERTA = ("aceita", "recusa", "duvida")


class JevError(RuntimeError):
    """Falha ao consultar o Jev."""


@dataclass(frozen=True)
class JevResult:
    intent: str
    intent_confidence: float
    publico: str
    publico_confidence: float
    resposta_oferta: str | None = None
    resposta_oferta_confidence: float = 0.0


def _perguntas(oferta_pendente: bool) -> dict[str, Any]:
    perguntas = {
        "intent": {
            "type": "choice",
            "instructions": (
                "Qual é a intenção da última mensagem do cliente?"
            ),
            "criteria": {
                "duvida": (
                    "Pergunta sobre produtos, portabilidade, documentos, prazos, "
                    "custos ou segurança."
                ),
                "suporte": (
                    "Relata dificuldade operacional para enviar um documento ou "
                    "seguir com o atendimento."
                ),
                "humano": (
                    "Pede explicitamente para falar com uma pessoa ou atendente."
                ),
            },
        },
        "publico": {
            "type": "choice",
            "instructions": (
                "A que público pertence o cliente, segundo a mensagem?"
            ),
            "criteria": {
                "clt": "Trabalhador com carteira assinada.",
                "inss": "Aposentado ou pensionista do INSS.",
                "servidor_publico": "Servidor público.",
                "autonomo": "Trabalhador autônomo.",
                "indefinido": "A mensagem não informa o público do cliente.",
            },
        },
    }
    if oferta_pendente:
        perguntas["resposta_oferta"] = {
            "type": "choice",
            "instructions": (
                "O cliente está aceitando, recusando ou ainda tem dúvida sobre "
                "a oferta de portabilidade apresentada?"
            ),
            "criteria": {
                "aceita": "Responde que quer seguir, aceita ou manda continuar.",
                "recusa": "Diz que não quer, dispensa ou recusa a oferta.",
                "duvida": "Faz uma pergunta ou não deixa claro se aceita.",
            },
        }
    return perguntas


def _choice(raw: Any, default: str) -> tuple[str, float]:
    if isinstance(raw, str):
        return raw, 1.0
    if not isinstance(raw, dict):
        return default, 0.0
    choice = raw.get("choice", raw.get("escolha", raw.get("value", default)))
    confidence: Any = raw.get(
        "confidence",
        raw.get("confianca", raw.get("probability", raw.get("probabilidade", 0.0))),
    )
    if not isinstance(choice, str) or not choice:
        choice = default
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    return choice, max(0.0, min(1.0, confidence))


def _parse(data: Any, oferta_pendente: bool) -> JevResult:
    if not isinstance(data, dict):
        raise JevError("Jev devolveu uma resposta inesperada")
    respostas = data.get("answers")
    if respostas is None:
        interno = data.get("data")
        if isinstance(interno, dict):
            respostas = interno.get("answers")
    if respostas is None:
        respostas = data
    if not isinstance(respostas, dict):
        raise JevError("Jev não devolveu respostas")

    intent, intent_conf = _choice(respostas.get("intent"), "duvida")
    publico, publico_conf = _choice(respostas.get("publico"), "indefinido")
    if intent not in INTENTS:
        intent, intent_conf = "duvida", 0.0
    if publico not in PUBLICOS:
        publico, publico_conf = "indefinido", 0.0

    resposta_oferta = None
    resposta_conf = 0.0
    if oferta_pendente:
        resposta_oferta, resposta_conf = _choice(
            respostas.get("resposta_oferta", respostas.get("respostaOferta")),
            "duvida",
        )
        if resposta_oferta not in RESPOSTAS_OFERTA:
            resposta_oferta, resposta_conf = "duvida", 0.0

    return JevResult(
        intent=intent,
        intent_confidence=intent_conf,
        publico=publico,
        publico_confidence=publico_conf,
        resposta_oferta=resposta_oferta,
        resposta_oferta_confidence=resposta_conf,
    )


def classify(message: str, oferta_pendente: bool = False) -> JevResult:
    """Classifica uma mensagem. Levanta ``JevError`` em qualquer falha."""

    settings = get_settings()
    if not settings.openrouter_api_key or not settings.jev_model:
        raise JevError("Jev não configurado")

    payload = {
        "model": settings.jev_model,
        "state": {"ultima_mensagem": message},
        "questions": _perguntas(oferta_pendente),
    }
    try:
        dados = openrouter.post_json(
            OPENROUTER_DECISIONS_URL,
            settings.openrouter_api_key,
            payload,
            JEV_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("jev_falhou: %s", type(exc).__name__)
        raise JevError("Falha ao consultar o Jev") from exc

    return _parse(dados, oferta_pendente)
