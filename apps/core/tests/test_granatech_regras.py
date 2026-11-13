"""Regras puras da Granatech: números, teto, ordem de status e normalização."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from saturday.bancos.granatech import status
from saturday.bancos.granatech.cliente import expira_em_segundos
from saturday.bancos.granatech.normalizacao import (
    Produto,
    Vinculo,
    id_da_proposta,
    itens_da_listagem,
    montar_corpo_proposta,
    normalizar_detalhe,
    normalizar_simulacao,
    recortar_detalhe,
)
from saturday.bancos.granatech.numeros import decimal_de
from saturday.bancos.granatech.teto import proxima_parcela

# ------------------------------------------------------------------ números


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1.500,00", Decimal("1500.00")),
        ("1500.00", Decimal("1500.00")),
        ("1.500", Decimal("1500")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("R$ 4.619,53", Decimal("4619.53")),
        ("4,9848", Decimal("4.9848")),
        (4619.53, Decimal("4619.53")),
        (300, Decimal("300")),
        ("0.5", Decimal("0.5")),
    ],
)
def test_decimal_de_le_os_formatos_da_api(entrada: object, esperado: Decimal) -> None:
    lido = decimal_de(entrada)
    assert lido == esperado
    assert isinstance(lido, Decimal)


@pytest.mark.parametrize("entrada", [True, None, "abc", "", [1]])
def test_decimal_de_recusa_o_que_nao_e_numero(entrada: object) -> None:
    with pytest.raises(ValueError):
        decimal_de(entrada)


# ------------------------------------------------------------------ teto


def test_primeira_tentativa_sem_folga() -> None:
    # 500 × 6999 / 8630,22 = 405,49…
    assert proxima_parcela(Decimal("500"), Decimal("8630.22"), Decimal("6999"), 1) == Decimal(
        "405.49"
    )


def test_tentativas_seguintes_tiram_meio_por_cento_cada() -> None:
    parcela, liberado, teto = Decimal("500"), Decimal("8630.22"), Decimal("6999")
    segunda = proxima_parcela(parcela, liberado, teto, 2)
    quarta = proxima_parcela(parcela, liberado, teto, 4)
    # floor(405,49… × 0,995) e floor(405,49… × 0,985)
    assert segunda == Decimal("403.46")
    assert quarta == Decimal("399.41")


def test_parcela_abaixo_de_45_nao_tem_oferta() -> None:
    assert proxima_parcela(Decimal("50"), Decimal("8000"), Decimal("6999"), 1) is None


# ------------------------------------------------------------------ status


def test_consulta_avanca_e_nao_regride() -> None:
    assert status.aceita_consulta(None, "AWAITING_CLIENT_AUTHORIZATION")
    assert status.aceita_consulta("AWAITING_CLIENT_AUTHORIZATION", "PROCESSING")
    assert not status.aceita_consulta("PROCESSING", "AWAITING_CLIENT_AUTHORIZATION")


@pytest.mark.parametrize("final", ["SUCCESS", "NO_MARGIN", "USED", "UNEXPECTED_ERROR"])
def test_consulta_final_nunca_e_sobrescrita(final: str) -> None:
    assert not status.aceita_consulta(final, "PROCESSING")
    assert not status.aceita_consulta(final, "SUCCESS")


@pytest.mark.parametrize(
    ("da_api_dev", "documentado"),
    [
        ("AGUARDANDO_AUTORIZACAO_DO_CLIENTE", "AWAITING_CLIENT_AUTHORIZATION"),
        ("CONCLUIDO", "SUCCESS"),
    ],
)
def test_status_de_consulta_em_portugues_vira_o_documentado(
    da_api_dev: str, documentado: str
) -> None:
    assert status.normalizar_consulta(da_api_dev) == documentado
    assert status.normalizar_consulta(documentado) == documentado
    assert status.normalizar_consulta("STATUS_NOVO") == "STATUS_NOVO"


def test_status_desconhecido_nao_e_aplicado() -> None:
    assert not status.aceita_consulta("PROCESSING", "STATUS_NOVO")
    assert not status.aceita_proposta("PENDING_CONFIRMATION", "STATUS_NOVO", None)


def test_evento_de_proposta_nos_dois_formatos() -> None:
    documentado = {"status_da_proposta": "PENDING_PAYMENT", "tipo_notificacao": "PROPOSTA_PAGA"}
    assert status.ler_evento_proposta(documentado) == ("PAYED", "PROPOSTA_PAGA")
    da_api_dev = {"tipo": "PROPOSTA", "status": "AGUARDANDO_CONFIRMACAO"}
    assert status.ler_evento_proposta(da_api_dev) == (
        "PENDING_CONFIRMATION",
        "AGUARDANDO_CONFIRMACAO",
    )
    assert status.ler_evento_proposta({"status": "NOVO"}) == ("NOVO", None)
    assert status.ler_evento_proposta({}) == ("", None)


def test_proposta_avanca_e_nao_regride() -> None:
    assert status.aceita_proposta(None, "PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO")
    assert status.aceita_proposta("PENDING_CONFIRMATION", "PENDING_FORMALIZATION", None)
    assert not status.aceita_proposta("PENDING_PAYMENT", "PENDING_FORMALIZATION", None)


def test_regressoes_legitimas_da_proposta() -> None:
    assert status.aceita_proposta(
        "PENDING_PAYMENT", "PENDING_REFORMALIZATION", "REFAZER_SEGURANCA_IDENTIDADE"
    )
    assert status.aceita_proposta("PENDING_PAYMENT", "PENDING_USER_REVIEW", "FALHA_PAGAMENTO")
    # Nem regressão legítima reabre uma proposta final.
    assert not status.aceita_proposta("PAYED", "PENDING_USER_REVIEW", "FALHA_PAGAMENTO")


@pytest.mark.parametrize("notificacao", ["PAGO", "PROPOSTA_PAGA"])
def test_pago_e_proposta_paga_valem_payed(notificacao: str) -> None:
    assert status.status_da_proposta("PENDING_PAYMENT", notificacao) == "PAYED"


# ------------------------------------------------------------------ token


def test_expira_em_aceita_os_formatos_do_login() -> None:
    agora = datetime(2026, 11, 11, 12, tzinfo=UTC)
    assert expira_em_segundos("1h", agora) == 3600
    assert expira_em_segundos("30m", agora) == 1800
    assert expira_em_segundos("45min", agora) == 2700
    assert expira_em_segundos(900, agora) == 900
    assert expira_em_segundos("900", agora) == 900
    fim = (agora + timedelta(minutes=20)).isoformat()
    assert expira_em_segundos(fim, agora) == 1200
    assert expira_em_segundos("amanhã", agora) == 3600
    assert expira_em_segundos(None, agora) == 3600


# ------------------------------------------------------------------ normalização


def _detalhe_da_dev() -> dict[str, Any]:
    return {
        "id": "c1",
        "margens": [
            {
                "id": "m1",
                "margem": "1.500,00",
                "nome_empregador": "Prime Tech LTDA",
                "documento_empregador": "12345678000190",
                "elegivel_empregador": True,
                "campo_fora_do_contrato": "x",
                "produtos": [
                    {
                        "id": "AAA36",
                        "nome": "AAA36",
                        "parcelas": [36],
                        "taxa_mensal": 4,
                        "seguro": True,
                        "margem": "1.500,00",
                        "limite_minimo": "500,00",
                        "limite_maximo": "50.000,00",
                        "id_empresa_seguro": 7,
                        "id_cobertura_seguro": 21,
                    }
                ],
            }
        ],
        "pessoa_natural": {
            "name": "FULANO",
            "document": "00189004967",
            "birth_date": "1990-05-15",
            "age": 36,
            "gender": "F",
            "mother_name": "MAE",
            "rg": "não está no contrato",
            "address": {"zip_code": "01001000", "uf": "SP", "lat": 1},
        },
    }


def test_detalhe_normalizado() -> None:
    detalhe = normalizar_detalhe(_detalhe_da_dev())

    assert detalhe is not None
    vinculo = detalhe.vinculos[0]
    assert vinculo.id_margem == "m1"
    assert vinculo.margem == Decimal("1500.00")
    produto = vinculo.produtos[0]
    assert produto.parcelas == (36,)
    assert produto.limite_maximo == Decimal("50000.00")
    assert produto.id_produto_seguro == "21"
    assert detalhe.pessoa is not None
    assert detalhe.pessoa.nascimento == date(1990, 5, 15)
    assert detalhe.pessoa.sexo == "F"


def test_detalhe_sem_margens_ainda_nao_esta_pronto() -> None:
    assert normalizar_detalhe({"id": "c1", "margens": [], "pessoa_natural": None}) is None


def test_recorte_guarda_so_o_contrato_e_relê_igual() -> None:
    recorte = recortar_detalhe(_detalhe_da_dev())

    assert "campo_fora_do_contrato" not in recorte["margens"][0]
    assert "rg" not in recorte["pessoa_natural"]
    assert "lat" not in recorte["pessoa_natural"]["address"]
    assert normalizar_detalhe(recorte) == normalizar_detalhe(_detalhe_da_dev())


def _simulacao(bloco: str) -> dict[str, Any]:
    return {
        bloco: {
            "valor_solicitado": 4619.53,
            "valor_parcela": 300,
            "numero_parcelas": 36,
            "taxa_mensal": 4,
            "taxa_anual": 60.1,
            "cet_mensal": "4,9848",
            "cet_anual": 79.27,
            "valor_iof": 175.28,
            "valor_seguro": 503.32,
            "valor_total_financiado": 5298.13,
            "valor_total_divida": "10.800,00",
            "parcelas": [{"dt_vencimento": "2026-12-20"}],
            "id_empregador": 501,
            "info_seguradora": {"id_externo": "SM-100000721-6"},
        }
    }


def test_simulacao_informa_o_bloco_que_voltou() -> None:
    com = normalizar_simulacao(_simulacao("resultado_da_simulacao_com_seguro"))
    sem = normalizar_simulacao(_simulacao("resultado_da_simulacao_sem_seguro"))

    assert com.seguro_aplicado and not sem.seguro_aplicado
    assert com.liberado == Decimal("4619.53")
    assert com.valor_total_divida == Decimal("10800.00")
    assert com.cet_mensal == Decimal("4.9848")
    assert com.primeiro_vencimento == date(2026, 12, 20)


def test_simulacao_vazia_e_erro() -> None:
    with pytest.raises(ValueError):
        normalizar_simulacao({})


def test_id_da_proposta_aceita_os_tres_formatos() -> None:
    assert id_da_proposta({"id": 10}) == "10"
    assert id_da_proposta({"id_proposta": "p1"}) == "p1"
    assert id_da_proposta({"data": {"id": "p2"}}) == "p2"
    assert id_da_proposta({"ok": True}) is None


def test_id_da_proposta_aceita_o_texto_puro_da_api_dev() -> None:
    """Rodada 10 da homologação: o 201 do POST /propostas é só o id, como texto JSON."""

    assert id_da_proposta("29ee4653-0c04-42b2-87da-1b24f66c111b") == (
        "29ee4653-0c04-42b2-87da-1b24f66c111b"
    )
    assert id_da_proposta("  ") is None


def test_itens_da_listagem() -> None:
    assert itens_da_listagem([{"id": 1}]) == [{"id": 1}]
    assert itens_da_listagem({"data": [{"id": 2}]}) == [{"id": 2}]
    assert itens_da_listagem({"nada": 1}) == []


def test_corpo_da_proposta_leva_seguro_e_valores_da_simulacao() -> None:
    simulacao = normalizar_simulacao(_simulacao("resultado_da_simulacao_com_seguro"))
    produto = Produto(
        id="AAA36",
        nome="AAA36",
        parcelas=(36,),
        taxa_mensal=Decimal(4),
        seguro=True,
        margem=None,
        limite_minimo=None,
        limite_maximo=None,
        id_empresa_seguro="7",
        id_produto_seguro="21",
    )
    vinculo = Vinculo(
        id_margem="m1",
        margem=Decimal(1500),
        nome_empregador="Prime Tech LTDA",
        documento_empregador="12345678000190",
        elegivel_empregador=True,
        produtos=(produto,),
    )

    corpo = montar_corpo_proposta(
        id_consulta="c1",
        vinculo=vinculo,
        produto=produto,
        simulacao=simulacao,
        tipo_empregador=1,
    )

    financeiro = corpo["informacoesFinanceira"][0]
    assert financeiro["valor_solicitado"] == 4619.53
    assert financeiro["valor_liberado_habilitado"] is True
    assert corpo["id_margem"] == "m1"
    assert corpo["informacaoDeSeguros"]["id_externo"] == "SM-100000721-6"

    # Teste da homologação na api-dev: `id_externo` vira a cobertura, como número.
    pela_cobertura = montar_corpo_proposta(
        id_consulta="c1",
        vinculo=vinculo,
        produto=produto,
        simulacao=simulacao,
        tipo_empregador=1,
        id_externo_da_cobertura=True,
    )
    assert pela_cobertura["informacaoDeSeguros"]["id_externo"] == 21
    assert pela_cobertura["informacoesFinanceira"] == corpo["informacoesFinanceira"]
