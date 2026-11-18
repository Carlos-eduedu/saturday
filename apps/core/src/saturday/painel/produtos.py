"""Panorama dos produtos para a aba Operação do painel.

Os números saem das constantes de regra de cada ramo: o painel só mostra, para
não existir uma segunda cópia das regras no front.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from saturday.agent.clt import regras as clt
from saturday.agent.clt.turno import reais
from saturday.bancos.c6 import regras as c6
from saturday.portabilidade import regras as inss
from saturday.settings import Settings

# Só para exibir: o nome de cada código citado nas regras de portabilidade.
NOMES = {
    "001": "Banco do Brasil",
    "012": "Inbursa",
    "033": "Santander",
    "070": "BRB",
    "104": "Caixa",
    "121": "Agibank",
    "237": "Bradesco",
    "254": "Paraná Banco",
    "341": "Itaú",
    "422": "Safra",
    "623": "Pan",
    "707": "Daycoval",
    "748": "Sicredi",
    "756": "Sicoob",
    "925": "BRB",
}


def _bancos(codigos: set[str]) -> str:
    return ", ".join(sorted({NOMES.get(c, c) for c in codigos}))


def _pct(valor: float | Decimal) -> str:
    return f"{valor:.2f}".replace(".", ",") + "% ao mês"


def _rs(valor: float | Decimal) -> str:
    return f"R$ {reais(Decimal(str(valor)))}"


def _grupo(titulo: str, *itens: tuple[str, str]) -> dict[str, Any]:
    return {"titulo": titulo, "itens": [{"rotulo": r, "valor": v} for r, v in itens]}


def produtos(settings: Settings) -> list[dict[str, Any]]:
    pagas = ", ".join(f"{NOMES.get(c, c)} {n}" for c, n in sorted(inss.PAGAS_MIN_POR_BANCO.items()))
    return [
        {
            "id": "portabilidade-inss",
            "nome": "Portabilidade INSS",
            "banco": {"id": "c6", "nome": "C6"},
            "situacao": "O agente calcula e oferece; o atendente digita no C6.",
            "grupos": [
                _grupo(
                    "Quem pode",
                    ("Idade", f"{inss.IDADE_MIN} a {inss.IDADE_MAX} anos"),
                    # shortcut: espécies fixas em hiscon.py, sem constante; trocar se virarem regra
                    ("Benefício não atendido", "BPC/LOAS (espécies 87 e 88)"),
                    (
                        "Contrato em papel",
                        f"{inss.IDADE_WEBPLUS} anos ou mais em "
                        + ", ".join(sorted(inss.UFS_WEBPLUS)),
                    ),
                ),
                _grupo(
                    "Contrato de origem",
                    ("Não porta", _bancos(inss.BANCOS_NAO_PORTA)),
                    ("Já é do C6", "fica fora da portabilidade"),
                    ("Taxa mínima", _pct(inss.TAXA_ORIGEM_MIN)),
                    ("Bancos de rede", f"{_bancos(inss.BANCOS_REDE)}: sem parcelas pagas mínimas"),
                    ("Parcelas pagas por banco", pagas),
                    (
                        "Demais bancos",
                        f"{inss.PAGAS_MIN_DEMAIS} parcelas pagas ou "
                        f"{inss.DIAS_INCLUSAO_ALTERNATIVA} dias, em contrato de "
                        f"{inss.PRAZO_ORIGINAL_EXIGE_CARENCIA}x",
                    ),
                ),
                _grupo(
                    "Contrato no C6 após a portabilidade",
                    ("Prazo", f"{inss.PRAZO_C6} parcelas"),
                    ("Valor mínimo", _rs(inss.CONTRATO_MINIMO)),
                    ("Sobra mínima", f"{_rs(inss.TROCO_MINIMO)} por contrato"),
                    ("Taxa do C6", f"até {_pct(inss.TAXA_TETO_C6 * 100)}"),
                ),
            ],
        },
        {
            "id": "contrato-novo-inss",
            "nome": "Contrato novo INSS (C6)",
            "banco": {"id": "c6", "nome": "C6"},
            "situacao": "O agente simula pela API do C6 e oferece; o atendente digita no C6.",
            "grupos": [
                _grupo(
                    "Quem pode",
                    ("Idade", f"{c6.IDADE_MIN} a {c6.IDADE_MAX} anos"),
                    ("Margem livre mínima", _rs(c6.MARGEM_MINIMA)),
                ),
                _grupo(
                    "Oferta",
                    ("Parcela pedida", f"{c6.FATOR_DA_MARGEM * 100:.0f}% da margem livre"),
                    ("Valor mínimo na conta", _rs(c6.VALOR_MINIMO)),
                    ("Taxa máxima", _pct(c6.TAXA_MAXIMA)),
                ),
                _grupo(
                    "Prazo e teto por idade",
                    *(
                        (
                            f"{de} anos" if de == ate else f"Até {ate} anos",
                            f"{prazo} parcelas, " + (f"até {_rs(teto)}" if teto else "sem teto"),
                        )
                        for de, ate, prazo, teto in c6.faixas()
                    ),
                ),
            ],
        },
        {
            "id": "clt",
            "nome": "Crédito do Trabalhador (CLT)",
            "banco": {"id": "granatech", "nome": "Granatech"},
            "situacao": "O agente consulta, simula e cria a proposta pela API.",
            "grupos": [
                _grupo(
                    "Quem pode",
                    ("Idade mínima", f"{clt.IDADE_MINIMA} anos"),
                    (
                        "Idade no fim do contrato",
                        f"até {clt.LIMITE_IDADE['F']} anos (mulher) "
                        f"ou {clt.LIMITE_IDADE['M']} anos (homem)",
                    ),
                    ("Tempo de casa mínimo", f"{clt.TEMPO_DE_CASA_MESES} meses"),
                    ("Empresa aberta há pelo menos", f"{clt.EMPRESA_IDADE_MINIMA_MESES} meses"),
                ),
                _grupo(
                    "Oferta",
                    ("Prazos", ", ".join(str(p) for p in clt.PRAZOS) + " parcelas"),
                    ("Valor liberado máximo", _rs(settings.granatech_teto_liberado)),
                    ("Novas simulações", f"até {clt.MAX_NOVAS_SIMULACOES}"),
                    ("Seguro", "incluído na oferta, com o valor, e opcional"),
                ),
                _grupo(
                    "Consulta",
                    ("Consentimento", "SIM do próprio cliente antes da consulta e da proposta"),
                    ("Cota diária", f"{settings.granatech_cota_diaria} consultas"),
                    ("Cota mensal", f"{settings.granatech_cota_mensal} consultas"),
                ),
            ],
        },
    ]
