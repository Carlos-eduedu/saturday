"""Métricas do turno, sem conteúdo de mensagem."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chamada:
    nome: str
    latencia_ms: float
    custo_usd: float | None = None
    # `ok`, `erro` ou o status HTTP do parceiro.
    status: str | None = None
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    # Id do modelo de IA chamado; mede a latência por modelo na aba Agente.
    modelo: str | None = None


@dataclass
class TurnMetrics:
    chamadas: list[Chamada] = field(default_factory=list)

    def registrar(
        self,
        nome: str,
        latencia_ms: float,
        custo_usd: float | None = None,
        *,
        status: str | None = None,
        tokens_entrada: int | None = None,
        tokens_saida: int | None = None,
        modelo: str | None = None,
    ) -> None:
        self.chamadas.append(
            Chamada(
                nome=nome,
                latencia_ms=round(latencia_ms, 2),
                custo_usd=custo_usd,
                status=status,
                tokens_entrada=tokens_entrada,
                tokens_saida=tokens_saida,
                modelo=modelo,
            )
        )

    @property
    def tokens_total(self) -> int:
        return sum((c.tokens_entrada or 0) + (c.tokens_saida or 0) for c in self.chamadas)

    @property
    def custo_total_usd(self) -> float:
        return sum(chamada.custo_usd for chamada in self.chamadas if chamada.custo_usd is not None)

    def resumo(self) -> dict[str, Any]:
        return {
            "chamadas": [
                {
                    "nome": chamada.nome,
                    "latencia_ms": chamada.latencia_ms,
                    "custo_usd": chamada.custo_usd,
                    "status": chamada.status,
                    "tokens_entrada": chamada.tokens_entrada,
                    "tokens_saida": chamada.tokens_saida,
                    **({"modelo": chamada.modelo} if chamada.modelo else {}),
                }
                for chamada in self.chamadas
            ],
            "custo_total_usd": round(self.custo_total_usd, 6),
            "tokens_total": self.tokens_total,
        }


_ATUAL: ContextVar[TurnMetrics | None] = ContextVar("saturday_metricas", default=None)


def iniciar_metricas() -> TurnMetrics:
    metricas = TurnMetrics()
    _ATUAL.set(metricas)
    return metricas


def metricas_atuais() -> TurnMetrics | None:
    return _ATUAL.get()


def registrar_chamada(
    nome: str,
    latencia_ms: float,
    custo_usd: float | None = None,
    *,
    status: str | int | None = None,
    tokens_entrada: int | None = None,
    tokens_saida: int | None = None,
    modelo: str | None = None,
) -> None:
    metricas = _ATUAL.get()
    if metricas is not None:
        metricas.registrar(
            nome,
            latencia_ms,
            custo_usd,
            status=None if status is None else str(status),
            tokens_entrada=tokens_entrada,
            tokens_saida=tokens_saida,
            modelo=modelo,
        )


def _inteiro(valor: object) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def uso_do_payload(dados: dict[str, Any]) -> dict[str, Any]:
    """Custo e tokens que a OpenRouter devolve em `usage` (vazio se não vier)."""

    usage = dados.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        "custo_usd": custo_do_payload(dados),
        "tokens_entrada": _inteiro(usage.get("prompt_tokens")),
        "tokens_saida": _inteiro(usage.get("completion_tokens")),
    }


def custo_do_payload(dados: dict[str, Any]) -> float | None:
    usage = dados.get("usage")
    if not isinstance(usage, dict):
        return None
    custo = usage.get("cost")
    if isinstance(custo, (int, float)) and not isinstance(custo, bool):
        return float(custo)
    return None
