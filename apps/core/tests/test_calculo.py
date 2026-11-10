"""Testes do cálculo puro de portabilidade (etapa 3)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from saturday.portabilidade.calculo import (
    DadosCliente,
    avaliar_contrato,
    calcular_portabilidade,
    competencia_referencia,
    parcelas_pagas,
    r2,
)
from saturday.portabilidade.hiscon import ContratoHiscon, Extrato
from saturday.portabilidade.regras import fora_da_cip

HOJE = date(2026, 10, 8)
EMISSAO = "08/10/2026"
CLIENTE = DadosCliente(data_nascimento=date(1962, 3, 12), uf="MS")


def inicio_para(pagas: int) -> str:
    """Mês de início que produz exatamente ``pagas`` na referência 09/2026."""

    ref = 2026 * 12 + 8  # setembro/2026 em índice zero-based
    indice = ref - (pagas - 1)
    return f"{indice % 12 + 1:02d}/{indice // 12}"


def contrato(
    banco: str,
    parcela: float,
    qtd: int,
    pagas: int,
    taxa: float,
    inclusao: str = "01/01/2020",
    situacao: str = "Ativo",
) -> ContratoHiscon:
    return ContratoHiscon(
        banco=banco,
        situacao=situacao,
        parcela=parcela,
        taxaMensal=taxa,
        qtdParcelas=qtd,
        inicioDesconto=inicio_para(pagas),
        dataInclusao=inclusao,
    )


def extrato(*contratos: ContratoHiscon, **extras: Any) -> Extrato:
    dados = {
        "ehHiscon": True,
        "especie": "32",
        "liberadoParaEmprestimo": True,
        "dataEmissao": "08/10/2026",
        "margemUtilizada": 0.0,
        "margemDisponivel": 0.0,
        "margemReservada": 0.0,
        "margemExtrapolada": 0.0,
        "contratos": list(contratos),
    }
    dados.update(extras)
    return Extrato.model_validate(dados)


CASOS_REFERENCIA = [
    ("643 - PINE", 295.24, 84, 23, 1.66, 11477.56, "240190", 1.699, 13927.54, 2449.98),
    ("033 - SANTANDER", 46.20, 84, 45, 2.09, 1223.90, "240178", 1.85, 2037.20, 813.29),
    ("041 - BANRISUL", 53.09, 84, 21, 1.80, 1990.86, "240182", 1.779, 2424.87, 434.01),
    ("935 - FACTA", 164.75, 96, 9, 1.85, 7098.05, "240182", 1.779, 7553.78, 455.73),
    ("341 - ITAÚ", 68.79, 91, 1, 1.59, 3280.39, "240234", 1.599, 3396.39, 116.00),
    ("389 - MERCANTIL", 48.19, 84, 54, 1.74, 1118.89, "240178", 1.8194, 2145.28, 1026.39),
    ("318 - BMG", 43.69, 96, 11, 1.70, 1956.73, "240190", 1.699, 2069.12, 112.39),
    ("079 - PICPAY", 47.88, 96, 9, 1.85, 2062.85, "240182", 1.779, 2195.30, 132.45),
]


@pytest.mark.parametrize(
    "banco,parcela,qtd,pagas,taxa,saldo,tabela,taxa_ref,liberado,troco",
    CASOS_REFERENCIA,
)
def test_casos_referencia_ao_centavo(
    banco: str,
    parcela: float,
    qtd: int,
    pagas: int,
    taxa: float,
    saldo: float,
    tabela: str | None,
    taxa_ref: float,
    liberado: float,
    troco: float,
) -> None:
    resultado = calcular_portabilidade(
        extrato(contrato(banco, parcela, qtd, pagas, taxa)),
        CLIENTE,
        HOJE,
    )

    c = resultado["contratos"][0]
    assert c["elegivel"] is True
    assert c["motivo"] == "ok"
    assert c["saldo_estimado"] == saldo
    assert c["tabela_refin"] == tabela
    assert c["taxa_refin"] == taxa_ref
    assert c["valor_liberado"] == liberado
    assert c["troco"] == troco


def test_competencia_e_parcelas_pagas() -> None:
    assert competencia_referencia(EMISSAO) == (2026, 9)
    assert parcelas_pagas(EMISSAO, "01/2023") == 45
    assert parcelas_pagas("08/01/2026", "01/2023") == 36  # referência 12/2025
    assert parcelas_pagas(EMISSAO, "01/2030") == 0


def test_r2_arredonda_como_javascript() -> None:
    assert r2(0.125) == 0.13
    assert r2(1.005) == 1.0  # floor(100.999...) — mesmo comportamento do JS
    assert r2(2082.483) == 2082.48


def test_daycoval_nao_porta() -> None:
    c = avaliar_contrato(contrato("707 - DAYCOVAL", 500, 84, 20, 2.0), EMISSAO)
    assert c["motivo"] == "banco_nao_porta"


def test_c6_ja_c6() -> None:
    c = avaliar_contrato(contrato("626 - C6", 500, 84, 20, 2.0), EMISSAO)
    assert c["motivo"] == "ja_c6"


def test_regras_de_cip() -> None:
    assert fora_da_cip("935") is False
    assert fora_da_cip("999") is False
    assert fora_da_cip("888") is True
    assert fora_da_cip("") is False
    assert fora_da_cip("033") is False


def test_codigo_fora_da_cip_barra_contrato() -> None:
    c = avaliar_contrato(contrato("888 - FINANCEIRA", 500, 84, 20, 2.0), EMISSAO)
    assert c["motivo"] == "banco_nao_porta"


def test_facta_935_nao_e_barrada_pela_cip() -> None:
    _, parcela, qtd, pagas, taxa, *_ = CASOS_REFERENCIA[3]
    c = avaliar_contrato(contrato("935 - FACTA", parcela, qtd, pagas, taxa), EMISSAO)
    assert c["motivo"] == "ok"


def test_pan_108x_30_pagas_insuficientes() -> None:
    c = avaliar_contrato(contrato("623 - PAN", 100, 108, 30, 1.8), EMISSAO)
    assert c["motivo"] == "pagas_insuficientes"


def test_corban_108x_5_pagas_com_400_dias_e_elegivel() -> None:
    c = avaliar_contrato(
        contrato("391 - CORBAN", 100, 108, 5, 2.0, inclusao="01/06/2025"),
        EMISSAO,
    )
    assert c["motivo"] == "ok"


def test_contrato_96x_com_uma_paga_e_elegivel() -> None:
    c = avaliar_contrato(contrato("318 - BMG", 50, 96, 1, 1.7), EMISSAO)
    assert c["motivo"] == "ok"


def test_santander_108x_zero_pagas_e_elegivel() -> None:
    c = avaliar_contrato(contrato("033 - SANTANDER", 50, 108, 0, 2.1), EMISSAO)
    assert c["motivo"] == "ok"


def test_taxa_abaixo_do_c6() -> None:
    c = avaliar_contrato(contrato("033 - SANTANDER", 100, 84, 10, 1.30), EMISSAO)
    assert c["motivo"] == "taxa_abaixo_c6"


def test_taxa_entre_135_e_140_aplica_redutor_de_90_por_cento() -> None:
    c = avaliar_contrato(contrato("033 - SANTANDER", 100, 84, 10, 1.38), EMISSAO)
    restantes = 84 - 10
    taxa = 0.0138
    saldo_sem_redutor = 100 * (1 - (1 + taxa) ** -restantes) / taxa
    assert c["saldo_estimado"] == r2(saldo_sem_redutor * 0.90)


def test_troco_abaixo_do_minimo() -> None:
    c = avaliar_contrato(contrato("643 - PINE", 1000, 96, 0, 1.9), EMISSAO)
    assert c["valor_liberado"] >= 2000
    assert c["troco"] < 50
    assert c["motivo"] == "troco_baixo"


def test_margem_extrapolada_aplica_desconto_no_maior_contrato() -> None:
    resultado = calcular_portabilidade(
        extrato(
            contrato("643 - PINE", 295.24, 84, 23, 1.66),
            contrato("033 - SANTANDER", 46.20, 84, 45, 2.09),
            margemExtrapolada=81.05,
        ),
        CLIENTE,
        HOJE,
    )

    pine, santander = resultado["contratos"]
    assert pine["desconto_margem"] == 81.10
    assert santander["desconto_margem"] is None


def test_alerta_de_refin_em_contrato_nao_elegivel() -> None:
    resultado = calcular_portabilidade(
        extrato(contrato("623 - PAN", 100, 108, 30, 1.8)),
        CLIENTE,
        HOJE,
    )
    c = resultado["contratos"][0]
    assert c["motivo"] == "pagas_insuficientes"
    assert c["alerta"] == "Sem portabilidade no C6 — oferecer refinanciamento"


def test_desconto_nao_e_aplicado_quando_nenhuma_parcela_supera_o_valor() -> None:
    resultado = calcular_portabilidade(
        extrato(
            contrato("643 - PINE", 295.24, 84, 23, 1.66),
            margemExtrapolada=1000.0,
        ),
        CLIENTE,
        HOJE,
    )
    assert resultado["contratos"][0]["desconto_margem"] is None


def test_alerta_de_refin_tambem_em_contrato_ilegivel_do_pan() -> None:
    resultado = calcular_portabilidade(
        extrato(contrato("623 - PAN", 100, 84, 10, 0)),
        CLIENTE,
        HOJE,
    )
    c = resultado["contratos"][0]
    assert c["motivo"] == "ilegivel"
    assert c["alerta"] == "Sem portabilidade no C6 — oferecer refinanciamento"


def test_desconto_ignora_contrato_nao_portavel_de_parcela_maior() -> None:
    """O desconto só pode ir para quem já seria elegível sem ele.

    Antes, o contrato de maior parcela levava o desconto mesmo quando não
    portava — e como ele não vira troco, o desconto simplesmente desaparecia.
    """

    resultado = calcular_portabilidade(
        extrato(
            contrato("707 - NAO PORTA", 800.00, 84, 23, 1.66),
            contrato("643 - PINE", 600.00, 84, 23, 1.66),
            margemExtrapolada=81.05,
        ),
        CLIENTE,
        HOJE,
    )

    nao_porta, pine = resultado["contratos"]
    assert nao_porta["elegivel"] is False
    assert nao_porta["desconto_margem"] is None
    assert pine["elegivel"] is True
    assert pine["desconto_margem"] == 81.10
