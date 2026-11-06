"""Todas as regras de portabilidade INSS → C6.

Nenhum número de regra deve ficar espalhado pelos outros módulos.
"""

from __future__ import annotations

from saturday.portabilidade.bancos_cip import CODIGOS_CIP

PRAZO_C6 = 108
PRAZO_96 = 96
TAXA_TETO_C6 = 0.0185  # taxa usada na ponderação do teto
MARGEM_SEGURANCA_PP = 0.10  # pontos percentuais, sempre aplicada
TAXA_ORIGEM_MIN = 1.35  # % a.m.
TROCO_MINIMO = 50.00  # R$ por contrato
CONTRATO_MINIMO = 2000.00  # R$, sobre o valor liberado (saldo + troco)
IOF_PCT_TROCO = 0.0324
FATOR_CARENCIA_EXPOENTE = 2.3
TOLERANCIA_CONFERENCIA = 1.00

IDADE_COLETA_MIN, IDADE_COLETA_MAX = 18, 110

IDADE_MIN, IDADE_MAX = 21, 73
# 21–71 → 108x (atendido). 72–73 → 96x (handoff idade_prazo_96 nesta versão).
IDADE_PRAZO_96_MIN = 72

BANCOS_C6 = {"336", "626"}  # motivo ja_c6
BANCOS_NAO_PORTA = {"707", "121", "012", "070", "925", "422", "260", "386"}
# Daycoval, Agibank, Inbursa, BRB (070 e 925), Safra, Nubank (260 e 386)
BANCOS_ALERTA_REFIN = {"623", "707"}  # Pan, Daycoval
BANCOS_REDE = {"001", "104", "237", "033", "341"}  # BB, Caixa, Bradesco, Santander, Itaú
PAGAS_MIN_POR_BANCO = {"623": 37, "254": 25}  # Pan, Paraná
PAGAS_MIN_DEMAIS = 12
DIAS_INCLUSAO_ALTERNATIVA = 360
PRAZO_ORIGINAL_EXIGE_CARENCIA = 108  # abaixo disso, sem carência

AJUSTE_SALDO_POR_BANCO = {"643": 23203.4 / 22785}  # Pine: +1,836%
FAIXA_REDUCAO_SALDO = (1.35, 1.40, 0.90)  # taxa origem nessa faixa: saldo × 0,90

UFS_WEBPLUS = {"PB", "AP", "TO", "RR"}  # com idade ≥ 60: alerta de contrato físico
IDADE_WEBPLUS = 60

FAIXA_OFERTA = (0.85, 1.05)  # faixa de sobra mostrada ao cliente

# Tabelas de refin da portabilidade, +30 dias de carência, 108x, canal WEB.
# Ordem = da maior para a menor taxa (e comissão). Vigência 28/10/2026.
TABELAS_REFIN = [
    ("240178", "Normal", 1.78, 1.85),
    ("240182", "Flex 1", 1.74, 1.779),
    ("240186", "Flex 2", 1.70, 1.739),
    ("240190", "Flex 3", 1.65, 1.699),
    ("240194", "Flex 4", 1.60, 1.649),
    ("240234", "Flex 5", 1.55, 1.599),
]


def _digitos(codigo: object) -> str:
    return "".join(ch for ch in str(codigo or "") if ch.isdigit())


def fora_da_cip(codigo: object) -> bool:
    """Aplica a regra de CIP da seção 8.3."""

    digitos = _digitos(codigo)
    if not digitos:
        return False
    if int(digitos) >= 900:
        return False
    return digitos.zfill(3) not in CODIGOS_CIP


# Nome usado no plano original.
foraDaCip = fora_da_cip
