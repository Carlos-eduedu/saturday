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


@dataclass
class TurnMetrics:
    chamadas: list[Chamada] = field(default_factory=list)

    def registrar(
        self,
        nome: str,
        latencia_ms: float,
        custo_usd: float | None = None,
    ) -> None:
        self.chamadas.append(
            Chamada(
                nome=nome,
                latencia_ms=round(latencia_ms, 2),
                custo_usd=custo_usd,
            )
        )

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
                }
                for chamada in self.chamadas
            ],
            "custo_total_usd": round(self.custo_total_usd, 6),
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
) -> None:
    metricas = _ATUAL.get()
    if metricas is not None:
        metricas.registrar(nome, latencia_ms, custo_usd)


def custo_do_payload(dados: dict[str, Any]) -> float | None:
    usage = dados.get("usage")
    if not isinstance(usage, dict):
        return None
    custo = usage.get("cost")
    if isinstance(custo, (int, float)) and not isinstance(custo, bool):
        return float(custo)
    return None
