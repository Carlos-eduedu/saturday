"""Motor de cálculo da portabilidade INSS → C6.

Toda a matemática fica aqui. Os valores finais (saldo, liberado e troco) são
arredondados com ``r2``; os intermediários seguem sem arredondamento.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from saturday.portabilidade.hiscon import ContratoHiscon, Extrato
from saturday.portabilidade.regras import (
    AJUSTE_SALDO_POR_BANCO,
    BANCOS_ALERTA_REFIN,
    BANCOS_C6,
    BANCOS_NAO_PORTA,
    BANCOS_REDE,
    CONTRATO_MINIMO,
    DIAS_INCLUSAO_ALTERNATIVA,
    FAIXA_OFERTA,
    FAIXA_REDUCAO_SALDO,
    FATOR_CARENCIA_EXPOENTE,
    IDADE_MAX,
    IDADE_MIN,
    IDADE_PRAZO_96_MIN,
    IDADE_WEBPLUS,
    IOF_PCT_TROCO,
    MARGEM_SEGURANCA_PP,
    PAGAS_MIN_DEMAIS,
    PAGAS_MIN_POR_BANCO,
    PRAZO_96,
    PRAZO_C6,
    PRAZO_ORIGINAL_EXIGE_CARENCIA,
    TABELAS_REFIN,
    TAXA_ORIGEM_MIN,
    TAXA_TETO_C6,
    TROCO_MINIMO,
    UFS_WEBPLUS,
    fora_da_cip,
)
from saturday.portabilidade.util import (
    contrato_ativo,
    parse_data,
    parse_mes_ano,
)
from saturday.settings import TZ_OPERACAO

ALERTA_REFIN = "Sem portabilidade no C6 — oferecer refinanciamento"


@dataclass(frozen=True)
class DadosCliente:
    data_nascimento: date
    uf: str | None = None


def r2(valor: float) -> float:
    """Arredondamento comercial, equivalente ao Math.round do JavaScript."""

    return math.floor(valor * 100 + 0.5) / 100


def _idade_em_anos(nascimento: date, hoje: date) -> int:
    anos = hoje.year - nascimento.year
    if (hoje.month, hoje.day) < (nascimento.month, nascimento.day):
        anos -= 1
    return anos


def idade_em_anos(data_nascimento: Any, hoje: date | None = None) -> int | None:
    nascimento = parse_data(data_nascimento)
    if nascimento is None:
        return None
    hoje = hoje or datetime.now(ZoneInfo(TZ_OPERACAO)).date()
    return _idade_em_anos(nascimento, hoje)


def competencia_referencia(data_emissao: Any) -> tuple[int, int]:
    """Mês de emissão menos um. Emissão 08/10/2026 → (2026, 9)."""

    emissao = parse_data(data_emissao)
    if emissao is None:
        raise ValueError("data de emissão inválida")
    ano, mes = emissao.year, emissao.month - 1
    if mes == 0:
        ano, mes = ano - 1, 12
    return ano, mes


def parcelas_pagas(data_emissao: Any, inicio_desconto: Any) -> int:
    ano_ref, mes_ref = competencia_referencia(data_emissao)
    inicio = parse_mes_ano(inicio_desconto)
    if inicio is None:
        return 0
    ano_inicio, mes_inicio = inicio
    return max(0, (ano_ref - ano_inicio) * 12 + (mes_ref - mes_inicio) + 1)


def _tabela_para(teto_seguro_pct: float) -> tuple[str, str, float, float] | None:
    for tabela in TABELAS_REFIN:
        if tabela[2] <= teto_seguro_pct + 1e-9:
            return tabela
    return None


def _preparar_contrato(contrato: ContratoHiscon) -> dict[str, Any]:
    return {
        "banco": contrato.banco,
        "banco_codigo": contrato.banco_codigo,
        "situacao": contrato.situacao,
        "parcela": contrato.parcela,
        "taxa_pct": contrato.taxaMensal,
        "qtd": contrato.qtdParcelas,
        "inicio": contrato.inicioDesconto,
        "inclusao": parse_data(contrato.dataInclusao),
        "legivel": contrato.legivel,
    }


def _carencia_cumprida(base: dict[str, Any], pagas: int, emissao: date) -> bool:
    qtd = int(base["qtd"] or 0)
    codigo = str(base["banco_codigo"])

    if qtd < PRAZO_ORIGINAL_EXIGE_CARENCIA:
        return True
    if codigo in BANCOS_REDE:
        return True
    if codigo in PAGAS_MIN_POR_BANCO:
        return pagas >= PAGAS_MIN_POR_BANCO[codigo]

    if pagas >= PAGAS_MIN_DEMAIS:
        return True
    inclusao = base["inclusao"]
    if not isinstance(inclusao, date):
        return False
    return (emissao - inclusao).days >= DIAS_INCLUSAO_ALTERNATIVA


def _desconto_margem(extrapolada: float | None) -> float:
    if extrapolada is None or extrapolada <= 0:
        return 0.0
    return math.ceil(r2(extrapolada * 10)) / 10


def _calcular_saldo(base: dict[str, Any], restantes: int) -> tuple[float, float]:
    taxa = float(base["taxa_pct"]) / 100
    parcela = float(base["parcela"])
    fator = (1 - (1 + taxa) ** -restantes) / taxa
    saldo = parcela * fator
    saldo *= AJUSTE_SALDO_POR_BANCO.get(base["banco_codigo"], 1.0)

    taxa_arredondada = round(taxa, 6)
    minimo, maximo, redutor = FAIXA_REDUCAO_SALDO
    if minimo / 100 <= taxa_arredondada <= maximo / 100:
        saldo *= redutor
    return saldo, taxa


def _avaliar(
    base: dict[str, Any],
    data_emissao: date,
    desconto: float = 0.0,
) -> dict[str, Any]:
    """Avalia um contrato já preparado. ``desconto`` só é usado neste contrato."""

    codigo = str(base["banco_codigo"])
    legivel = bool(base["legivel"])
    resultado: dict[str, Any] = {
        "banco_codigo": codigo,
        "banco": base["banco"],
        "situacao": base["situacao"],
        "parcela": base["parcela"],
        "taxa_origem": base["taxa_pct"],
        "qtd_parcelas": base["qtd"],
        "pagas": None,
        "restantes": None,
        "saldo_estimado": None,
        "tabela_refin": None,
        "taxa_refin": None,
        "valor_liberado": None,
        "troco": None,
        "desconto_margem": None,
        "elegivel": False,
        "motivo": "ilegivel",
        "alerta": None,
    }

    if not legivel:
        if codigo in BANCOS_ALERTA_REFIN:
            resultado["alerta"] = ALERTA_REFIN
        return resultado

    pagas = parcelas_pagas(data_emissao, base["inicio"])
    restantes = max(1, int(base["qtd"]) - pagas)
    resultado["pagas"] = pagas
    resultado["restantes"] = restantes

    saldo, taxa = _calcular_saldo(base, restantes)
    saldo_final = r2(saldo)
    resultado["saldo_estimado"] = saldo_final

    teto = (taxa * restantes + TAXA_TETO_C6 * (PRAZO_C6 - restantes)) / PRAZO_C6
    teto_seguro = (
        (taxa - MARGEM_SEGURANCA_PP / 100) * restantes + TAXA_TETO_C6 * (PRAZO_C6 - restantes)
    ) / PRAZO_C6
    tabela = _tabela_para(teto_seguro * 100)
    if tabela is not None:
        resultado["tabela_refin"] = tabela[0]
        taxa_refin = min(tabela[3] / 100, teto)
        resultado["taxa_refin"] = round(taxa_refin * 100, 4)

        parcela_nova = float(base["parcela"]) - desconto
        if desconto > 0:
            resultado["desconto_margem"] = desconto
        financiado = (
            parcela_nova
            * (1 - (1 + taxa_refin) ** -PRAZO_C6)
            / taxa_refin
            * (1 + taxa_refin) ** -FATOR_CARENCIA_EXPOENTE
        )
        liberado = (financiado + IOF_PCT_TROCO * saldo) / (1 + IOF_PCT_TROCO)
        resultado["valor_liberado"] = r2(liberado)
        resultado["troco"] = r2(liberado - saldo)

    if not contrato_ativo(base["situacao"]):
        motivo = "nao_ativo"
    elif codigo in BANCOS_C6:
        motivo = "ja_c6"
    elif codigo in BANCOS_NAO_PORTA or fora_da_cip(codigo):
        motivo = "banco_nao_porta"
    elif not _carencia_cumprida(base, pagas, data_emissao):
        motivo = "pagas_insuficientes"
    elif taxa * 100 < TAXA_ORIGEM_MIN:
        motivo = "taxa_abaixo_c6"
    elif tabela is None:
        motivo = "sem_tabela"
    elif resultado["valor_liberado"] < CONTRATO_MINIMO:
        motivo = "abaixo_minimo_c6"
    elif resultado["troco"] < TROCO_MINIMO:
        motivo = "troco_baixo"
    else:
        motivo = "ok"

    resultado["motivo"] = motivo
    resultado["elegivel"] = motivo == "ok"
    if motivo not in {"ok", "nao_ativo"} and codigo in BANCOS_ALERTA_REFIN:
        resultado["alerta"] = ALERTA_REFIN
    return resultado


def _contrato_para_desconto(
    bases: list[dict[str, Any]],
    desconto: float,
) -> int | None:
    candidatos = [
        (indice, base["parcela"])
        for indice, base in enumerate(bases)
        if base["legivel"] and contrato_ativo(base["situacao"]) and base["parcela"] > desconto
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda item: item[1])[0]


def avaliar_contrato(
    contrato: ContratoHiscon,
    data_emissao: Any,
    desconto: float = 0.0,
) -> dict[str, Any]:
    """Avalia um único contrato. Útil para testes e diagnóstico."""

    emissao = parse_data(data_emissao)
    if emissao is None:
        raise ValueError("data de emissão inválida")
    return _avaliar(_preparar_contrato(contrato), emissao, desconto)


def calcular_portabilidade(
    extrato: Extrato,
    cliente: DadosCliente | None = None,
    hoje: date | None = None,
) -> dict[str, Any]:
    """Calcula o resultado de portabilidade a partir do extrato tipado."""

    hoje = hoje or datetime.now(ZoneInfo(TZ_OPERACAO)).date()

    emissao = parse_data(extrato.dataEmissao)
    contratos = list(extrato.contratos)
    especie = extrato.especie
    bloqueado = extrato.liberadoParaEmprestimo is False

    resultado: dict[str, Any] = {
        "ok": True,
        "motivo": None,
        "prazo": PRAZO_C6,
        "beneficio_bloqueado": bloqueado,
        "alerta_webplus": False,
        "troco_total": 0.0,
        "troco_faixa": {"min": 0.0, "max": 0.0},
        "contratos": [],
    }

    if especie in {"87", "88"}:
        resultado.update(ok=False, motivo="especie_nao_atendida")
        return resultado

    if cliente is None or not isinstance(cliente.data_nascimento, date):
        resultado.update(ok=False, motivo="dados_cliente_nao_informados")
        return resultado

    idade = _idade_em_anos(cliente.data_nascimento, hoje)
    uf = (cliente.uf or "").strip().upper()
    alerta_webplus = bool(idade >= IDADE_WEBPLUS and uf in UFS_WEBPLUS)
    resultado["alerta_webplus"] = alerta_webplus

    if idade < IDADE_MIN or idade > IDADE_MAX:
        resultado.update(ok=False, motivo="idade_fora_regra")
        return resultado
    if idade >= IDADE_PRAZO_96_MIN:
        resultado.update(ok=False, motivo="idade_prazo_96", prazo=PRAZO_96)
        return resultado

    if emissao is None:
        raise ValueError("data de emissão inválida")

    bases = [_preparar_contrato(contrato) for contrato in contratos]
    desconto = _desconto_margem(extrato.margemExtrapolada)
    indice_desconto = _contrato_para_desconto(bases, desconto) if desconto > 0 else None

    avaliados = []
    for indice, base in enumerate(bases):
        aplicado = desconto if indice == indice_desconto else 0.0
        avaliado = _avaliar(base, emissao, aplicado)
        if avaliado["troco"] is not None:
            troco = avaliado["troco"]
            avaliado["troco_faixa"] = {
                "min": r2(troco * FAIXA_OFERTA[0]),
                "max": r2(troco * FAIXA_OFERTA[1]),
            }
        else:
            avaliado["troco_faixa"] = {"min": 0.0, "max": 0.0}
        avaliados.append(avaliado)

    total = r2(sum(c["troco"] for c in avaliados if c["elegivel"]))
    resultado["contratos"] = avaliados
    resultado["troco_total"] = total
    resultado["troco_faixa"] = {
        "min": r2(total * FAIXA_OFERTA[0]),
        "max": r2(total * FAIXA_OFERTA[1]),
    }
    return resultado
