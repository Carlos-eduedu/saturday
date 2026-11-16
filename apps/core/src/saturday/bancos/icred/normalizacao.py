"""Leitura da `Consulta` que o motor do iCred devolve.

Só passa adiante o que o cliente pode ver. A comissão (`comissao_rs`, `pct`,
`comissao`) é descartada aqui: não entra no estado, na ficha nem em log
(decisão 0027). Dinheiro vira texto de ``Decimal`` para caber no JSON do estado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from saturday.bancos.granatech.numeros import decimal_ou_none

TIPOS = frozenset({"port", "port_refin", "refin", "novo"})
COM_OFERTA = "COM_OFERTA"
ESTADOS_FINAIS = frozenset({"concluida", "cancelada"})


@dataclass(frozen=True)
class Resultado:
    id_externo: str
    estado: str
    situacao: str | None
    # Um dict por contrato: tipo, produto, banco, taxa, prazo, parcela, liberado.
    contratos: list[dict[str, Any]]
    # Falso quando algum contrato veio sem um número que a oferta precisa dizer.
    completo: bool
    valido_ate: datetime | None

    @property
    def final(self) -> bool:
        return self.estado in ESTADOS_FINAIS


def _contrato(produto: dict[str, Any]) -> dict[str, Any] | None:
    try:
        taxa = decimal_ou_none(produto.get("taxa"))
        parcela = decimal_ou_none(produto.get("parcela"))
        liberado = decimal_ou_none(produto.get("liberado"))
        prazo = int(produto["prazo"])
    except KeyError, TypeError, ValueError:
        return None
    tipo = produto.get("tipo")
    if tipo not in TIPOS or taxa is None or parcela is None or liberado is None:
        return None
    return {
        "tipo": tipo,
        "produto": produto.get("produto"),
        "banco": produto.get("banco"),
        "taxa": str(taxa),
        "prazo": prazo,
        "parcela": str(parcela),
        "liberado": str(liberado),
    }


def _data_hora(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        lido = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return lido if lido.tzinfo else None


def normalizar_consulta(dados: dict[str, Any]) -> Resultado:
    """Levanta ``ValueError`` quando falta o id ou o estado."""

    id_externo = dados.get("id")
    estado = dados.get("estado")
    if not isinstance(id_externo, str) or not isinstance(estado, str):
        raise ValueError("consulta do iCred sem id ou estado")
    brutos = [p for p in dados.get("produtos") or [] if isinstance(p, dict)]
    contratos = [c for c in map(_contrato, brutos) if c is not None]
    situacao = dados.get("situacao")
    return Resultado(
        id_externo=id_externo,
        estado=estado,
        situacao=situacao if isinstance(situacao, str) else None,
        contratos=contratos,
        completo=len(contratos) == len(brutos),
        valido_ate=_data_hora(dados.get("valido_ate")),
    )
