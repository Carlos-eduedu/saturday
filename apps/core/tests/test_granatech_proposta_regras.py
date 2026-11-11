"""Ação da conversa por evento de proposta e corpo dos dados do tomador."""

from __future__ import annotations

from datetime import date

import pytest

from saturday.bancos.granatech import status
from saturday.bancos.granatech.normalizacao import Endereco, Pessoa, montar_dados_tomador


@pytest.mark.parametrize(
    ("st", "notificacao", "acao"),
    [
        ("PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO", "criada"),
        ("PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO", "formalizar"),
        ("PENDING_FORMALIZATION", "BLOQUEIO_DE_SALDO_EM_ANDAMENTO", "silencio"),
        ("PENDING_FORMALIZATION", "FORMALIZACAO_EM_ANDAMENTO", "silencio"),
        ("PENDING_FORMALIZATION", "BLOQUEIO_SALDO", "silencio"),
        ("PENDING_REFORMALIZATION", "REFAZER_SEGURANCA_IDENTIDADE", "refazer"),
        ("PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO", "analise"),
        ("PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE", "identidade_ok"),
        ("PENDING_USER_REVIEW", "AGUARDANDO_REVISAO_USUARIO", "revisao"),
        ("PENDING_USER_REVIEW", "FALHA_PAGAMENTO", "falha_pagamento"),
        ("REPROVED", "REPROVADO", "reprovada"),
        ("CANCELED", "QUALQUER_COISA", "cancelada"),
        ("CANCELED_BY_CLIENT", None, "cancelada"),
        ("PAYED", "PAGO", "paga"),
        (None, "PROPOSTA_PAGA", "paga"),
        ("PENDING_PAYMENT", None, "identidade_ok"),
        ("STATUS_NOVO", "NOTIFICACAO_NOVA", "desconhecida"),
    ],
)
def test_acao_da_proposta(st: str | None, notificacao: str | None, acao: str) -> None:
    assert status.acao_da_proposta(st, notificacao) == acao


def test_dados_tomador() -> None:
    pessoa = Pessoa(
        nome="CLIENTE DE TESTE",
        cpf="00189004967",
        nascimento=date(1990, 5, 15),
        idade=36,
        sexo="M",
        nome_mae="MAE DE TESTE",
        estado_civil="SOLTEIRO",
        email=None,
        telefone=None,
        endereco=Endereco("01001000", "PRACA DA SE", "100", "", "SE", "SAO PAULO", "SP"),
    )
    corpo = montar_dados_tomador(
        pessoa=pessoa,
        cpf="00189004967",
        nome="Cliente de Teste",
        estado_civil="CASADO",
        celular="11987654321",
        conta={
            "banco_codigo": "341",
            "agencia": "1234",
            "digito_agencia": "",
            "numero_conta": "56789",
            "digito_conta": "0",
            "tipo_conta": "conta_corrente",
        },
    )
    assert corpo["nome_completo_mae"] == "MAE DE TESTE"
    assert corpo["data_nascimento"] == "1990-05-15"
    assert corpo["estado"] == "SP" and corpo["cep"] == "01001000"
    assert corpo["estado_civil"] == "CASADO"
    assert corpo["tipo_dados_bancarios"] == "dados_bancarios"
    assert corpo["banco_detalhe"]["banco_codigo"] == "341"
