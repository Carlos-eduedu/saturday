"""Classificação de intenção pelo Jev, via OpenRouter Decisions API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from saturday.services.openrouter import OpenRouterClient, OpenRouterError
from saturday.settings import JEV_INTENT_THRESHOLD, JEV_TIMEOUT_S, Settings

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
    probabilities: dict[str, dict[str, float]] = field(default_factory=dict)

    def probabilidade(self, pergunta: str, rotulo: str) -> float:
        return self.probabilities.get(pergunta, {}).get(rotulo, 0.0)

    @property
    def pediu_humano(self) -> bool:
        return self.probabilidade("intent", "humano") >= JEV_INTENT_THRESHOLD

    @property
    def aceitou_oferta(self) -> bool:
        return self.probabilidade("resposta_oferta", "aceita") >= JEV_INTENT_THRESHOLD

    @property
    def recusou_oferta(self) -> bool:
        return self.probabilidade("resposta_oferta", "recusa") >= JEV_INTENT_THRESHOLD


def _perguntas(oferta_pendente: bool) -> dict[str, Any]:
    perguntas: dict[str, Any] = {
        "intent": {
            "type": "choice",
            "instructions": "Qual é a intenção da última mensagem do cliente?",
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
                    "Pede para falar com uma pessoa, atendente ou humano, ou pede "
                    "uma ligação. NÃO conta: perguntar se o atendimento é feito por "
                    "uma pessoa, reclamar sem pedir uma pessoa, ou citar "
                    '"atendente" em outro contexto.'
                ),
            },
        },
        "publico": {
            "type": "choice",
            "instructions": "A que público pertence o cliente, segundo a mensagem?",
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
                "aceita": (
                    "Diz que quer seguir, aceita ou manda continuar (ex.: 'sim', "
                    "'pode fazer', 'quero', 'vamos'). NÃO conta: 'ok' ou 'entendi' "
                    "sozinhos depois de uma explicação, nem perguntas."
                ),
                "recusa": (
                    "Diz que não quer (ex.: 'não', 'não quero', 'agora não'). "
                    "NÃO conta: dúvida sobre valor, prazo ou segurança."
                ),
                "duvida": "Faz uma pergunta ou não deixa claro se aceita.",
            },
        }
    return perguntas


def _probabilidades(raw: dict[str, Any]) -> dict[str, float]:
    valores = raw.get("probabilities")
    if not isinstance(valores, dict):
        return {}
    resultado: dict[str, float] = {}
    for rotulo, valor in valores.items():
        if not isinstance(rotulo, str):
            continue
        try:
            numero = float(valor)
        except TypeError, ValueError:
            continue
        resultado[rotulo] = max(0.0, min(1.0, numero))
    return resultado


def _choice(raw: Any, default: str) -> tuple[str, float, dict[str, float]]:
    if isinstance(raw, str):
        # Texto puro não traz confiança: não pode disparar uma decisão.
        return raw, 0.0, {}
    if not isinstance(raw, dict):
        return default, 0.0, {}
    choice = raw.get("choice", raw.get("escolha", raw.get("value", default)))
    confidence: Any = raw.get(
        "confidence",
        raw.get("confianca", raw.get("probability", raw.get("probabilidade", 0.0))),
    )
    if not isinstance(choice, str) or not choice:
        choice = default
    try:
        confidence = float(confidence)
    except TypeError, ValueError:
        confidence = 0.0
    return (
        choice,
        max(0.0, min(1.0, confidence)),
        _probabilidades(raw),
    )


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

    intent, intent_conf, intent_probs = _choice(respostas.get("intent"), "duvida")
    publico, publico_conf, publico_probs = _choice(respostas.get("publico"), "indefinido")
    probabilities = {"intent": intent_probs, "publico": publico_probs}
    if intent not in INTENTS:
        intent, intent_conf = "duvida", 0.0
        probabilities["intent"] = {}
    if publico not in PUBLICOS:
        publico, publico_conf = "indefinido", 0.0
        probabilities["publico"] = {}

    resposta_oferta = None
    resposta_conf = 0.0
    if oferta_pendente:
        resposta_oferta, resposta_conf, resposta_probs = _choice(
            respostas.get("resposta_oferta", respostas.get("respostaOferta")),
            "duvida",
        )
        if resposta_oferta not in RESPOSTAS_OFERTA:
            resposta_oferta, resposta_conf = "duvida", 0.0
            resposta_probs = {}
        probabilities["resposta_oferta"] = resposta_probs

    return JevResult(
        intent=intent,
        intent_confidence=intent_conf,
        publico=publico,
        publico_confidence=publico_conf,
        resposta_oferta=resposta_oferta,
        resposta_oferta_confidence=resposta_conf,
        probabilities=probabilities,
    )


class JevClient:
    """Cliente do Jev para uma instância da aplicação."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._settings = settings
        self._openrouter = OpenRouterClient(
            http,
            settings.openrouter_api_key.get_secret_value(),
        )

    def classify(
        self,
        message: str,
        oferta_pendente: bool = False,
        oferta: str | None = None,
    ) -> JevResult:
        """Classifica uma mensagem. Levanta ``JevError`` em qualquer falha."""

        if not self._settings.openrouter_api_key.get_secret_value():
            raise JevError("Jev não configurado")
        if not self._settings.jev_model:
            raise JevError("Jev não configurado")

        state: dict[str, Any] = {"ultima_mensagem": message}
        if oferta_pendente:
            state["ultima_mensagem_agente"] = oferta or ""

        payload = {
            "model": self._settings.jev_model,
            "state": state,
            "questions": _perguntas(oferta_pendente),
        }
        try:
            dados = self._openrouter.post_json(
                OPENROUTER_DECISIONS_URL,
                payload,
                JEV_TIMEOUT_S,
            )
        except OpenRouterError as exc:
            logger.warning("jev_falhou: %s", type(exc).__name__)
            raise JevError("Falha ao consultar o Jev") from exc

        return _parse(dados, oferta_pendente)
