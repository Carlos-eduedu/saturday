"""O que fazer com o resultado de uma consulta ao iCred (decisão 0027).

Tudo em código (regra 2). O motor escolhe a tabela; aqui se confere o que pode
ser apresentado.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from saturday.bancos.icred.normalizacao import COM_OFERTA

# Mesma política da decisão 0026: nada acima desta taxa ao mês é oferecido.
TAXA_MAXIMA = Decimal("1.85")
# Situações que só um atendente resolve.
BLOQUEIOS = frozenset({"JA_GRAVADO", "PROPOSTA_EXISTENTE", "TELEFONE_VINCULADO"})
# O valor gravado nesses tipos pode diferir do mostrado: a oferta é estimativa.
TIPOS_ESTIMADOS = frozenset({"port", "port_refin"})

OFERTA = "oferta"
HANDOFF = "handoff"
SEGUIR = "seguir"


def total_na_conta(contratos: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(c["liberado"]) for c in contratos), Decimal(0))


def eh_estimativa(contratos: list[dict[str, Any]]) -> bool:
    return any(c["tipo"] in TIPOS_ESTIMADOS for c in contratos)


def decidir(
    situacao: str | None, contratos: list[dict[str, Any]] | None, valor_c6: Decimal
) -> tuple[str, str | None]:
    """Devolve ``(OFERTA | HANDOFF | SEGUIR, motivo do handoff)``.

    ``valor_c6`` é o que a portabilidade C6 põe na conta do cliente (zero sem
    contrato elegível). ``SEGUIR`` é o caminho de antes do iCred.
    """

    if situacao in BLOQUEIOS:
        return HANDOFF, "icred_bloqueio"
    if situacao != COM_OFERTA:
        return SEGUIR, None
    if not contratos:
        # Oferta que não deu para ler inteira: apresentar parte quebraria a regra 3.
        return HANDOFF, "icred_conferir"
    if any(Decimal(c["taxa"]) > TAXA_MAXIMA for c in contratos):
        return HANDOFF, "icred_taxa_alta"
    # O C6 ganha no empate.
    if total_na_conta(contratos) <= valor_c6:
        return SEGUIR, None
    return OFERTA, None
