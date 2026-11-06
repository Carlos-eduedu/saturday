"""Mensagens fixas do fluxo de portabilidade.

Nenhum texto com valores é gerado por LLM. Os valores vêm exclusivamente de
``portability_result`` e são formatados aqui.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

MENSAGEM_IDADE_FORA = (
    "No momento não atendemos clientes com idade abaixo de 21 ou acima de 73 "
    "anos. Vou te transferir para um atendente da MEX."
)

MENSAGEM_IDADE_96 = (
    "Para clientes com 72 ou 73 anos, o prazo é de 96 parcelas, que ainda não "
    "está disponível nesta versão do atendimento. Vou te transferir para um "
    "atendente da MEX."
)

MENSAGEM_ESPECIE_NAO_ATENDIDA = (
    "Benefícios do BPC/LOAS (espécies 87 e 88) não são atendidos por esta "
    "portabilidade. Vou te transferir para um atendente da MEX."
)


def formatar_valor(valor: float | int | None) -> str:
    """Reais inteiros, truncados para baixo, com ponto de milhar."""

    if valor is None:
        valor = 0
    inteiro = math.floor(float(valor))
    return f"{inteiro:,}".replace(",", ".")


def nome_banco_curto(banco: str | None) -> str:
    if not banco:
        return "banco atual"
    nome = banco
    if " - " in banco:
        nome = banco.split(" - ", 1)[1]
    nome = nome.strip()
    if not nome:
        return "banco atual"
    especiais = {
        "BMG": "BMG",
        "C6": "C6",
        "ITAU": "Itaú",
        "ITAÚ": "Itaú",
        "PICPAY": "PicPay",
        "BB": "BB",
    }
    return especiais.get(nome.upper(), nome.title())


def _faixa(contrato: dict[str, Any]) -> tuple[float, float]:
    faixa = contrato.get("troco_faixa") or {}
    return faixa.get("min", 0.0), faixa.get("max", 0.0)


def mensagem_oferta(resultado: dict[str, Any], uf: str | None = None) -> str:
    contratos = [c for c in resultado.get("contratos", []) if c.get("elegivel")]
    faixa_total = resultado.get("troco_faixa") or {}
    linhas = [
        "Analisei o seu extrato. Dá para trazer "
        f"{len(contratos)} contrato(s) para o C6, e a sobra para você fica, "
        "aproximadamente, entre "
        f"R$ {formatar_valor(faixa_total.get('min'))} e "
        f"R$ {formatar_valor(faixa_total.get('max'))}."
    ]

    for contrato in contratos:
        minimo, maximo = _faixa(contrato)
        linhas.append(
            f"• {contrato.get('banco')}: entre R$ {formatar_valor(minimo)} "
            f"e R$ {formatar_valor(maximo)}"
        )

    linhas.append("")
    linhas.extend(
        [
            "O valor é aproximado: o valor certo só sai quando o seu banco atual "
            "informar o saldo devedor.",
            "O processo leva de 10 a 15 dias úteis, e a MEX não cobra nada de você.",
            "Se o seu banco atual oferecer uma contraproposta e você aceitar, a "
            "portabilidade é cancelada.",
        ]
    )
    if resultado.get("beneficio_bloqueado"):
        linhas.append(
            "Antes de seguir, é preciso desbloquear o benefício para empréstimo "
            "no app Meu INSS."
        )
    if resultado.get("alerta_webplus"):
        linhas.append(
            f"Como você tem mais de 60 anos e mora em {uf or ''}, além da selfie "
            "será preciso assinar o contrato em papel."
        )

    linhas.extend(["", "Quer seguir com a portabilidade?"])
    return "\n".join(linhas)


MOTIVOS = {
    "banco_nao_porta": "o C6 não faz portabilidade de contratos do {banco}",
    "ja_c6": "o contrato do {banco} já está no C6",
    "nao_ativo": "o contrato do {banco} não está ativo",
    "pagas_insuficientes": "ainda faltam parcelas pagas no contrato do {banco}",
    "taxa_abaixo_c6": "a taxa do contrato do {banco} está abaixo da mínima do C6",
    "sem_tabela": (
        "não há uma tabela de refinanciamento disponível para o contrato do {banco}"
    ),
    "abaixo_minimo_c6": (
        "o contrato do {banco} está abaixo do valor mínimo de portabilidade"
    ),
    "troco_baixo": "a sobra do contrato do {banco} ficaria abaixo do mínimo",
    "ilegivel": "não consegui ler os dados do contrato do {banco}",
}

PRIORIDADE_MOTIVOS = (
    "banco_nao_porta",
    "ja_c6",
    "nao_ativo",
    "pagas_insuficientes",
    "taxa_abaixo_c6",
    "sem_tabela",
    "abaixo_minimo_c6",
    "troco_baixo",
    "ilegivel",
)


def _motivo_principal(resultado: dict[str, Any]) -> str | None:
    contratos = [c for c in resultado.get("contratos", []) if not c.get("elegivel")]
    if not contratos:
        return None

    contagem = Counter(c.get("motivo") for c in contratos)
    ordem = {motivo: indice for indice, motivo in enumerate(PRIORIDADE_MOTIVOS)}
    return str(
        min(
            contagem,
            key=lambda motivo: (-contagem[motivo], ordem.get(motivo, 99)),
        )
    )



def mensagem_sem_portabilidade(resultado: dict[str, Any]) -> str:
    motivo = _motivo_principal(resultado)
    if motivo is None:
        return (
            "Analisei o seu extrato, mas não encontrei um contrato com "
            "portabilidade para o C6. Vou te transferir para um atendente da MEX."
        )

    contrato = next(
        c
        for c in resultado.get("contratos", [])
        if not c.get("elegivel") and c.get("motivo") == motivo
    )
    banco = nome_banco_curto(contrato.get("banco"))
    explicacao = MOTIVOS[motivo].format(banco=banco)
    return (
        f"Analisei o seu extrato, mas não encontrei um contrato com "
        f"portabilidade para o C6: {explicacao}. Vou te transferir para um "
        "atendente da MEX."
    )
