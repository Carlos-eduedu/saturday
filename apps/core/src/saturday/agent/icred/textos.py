"""Textos fixos do iCred. Os números vêm do código, nunca do modelo (regra 2)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from saturday.agent.clt.turno import reais
from saturday.agent.icred.regras import eh_estimativa, total_na_conta

# Versão dos textos de consentimento e de aceite, gravada com a prova.
VERSAO = "icred-1"
# O mesmo pedido de consulta quando o C6 já falou na conversa.
VERSAO_DEPOIS_C6 = "icred-1-depois-c6"

# Só a abertura muda entre os dois pedidos. Mudou o texto, mude a versão: a
# prova guarda os dois.
_PEDIDO = (
    "posso consultar também "
    "o iCred, um banco parceiro, para ver se ele tem uma condição melhor para "
    "você. Para isso vou usar o seu CPF e este número de telefone. Posso "
    "consultar? Responda *SIM* ou *NÃO*."
)
PEDIR_SIM = "Recebi o seu extrato. Antes de te passar o resultado, " + _PEDIDO
# Depois do C6 o extrato não acabou de chegar.
PEDIR_SIM_DEPOIS_C6 = "Antes de continuar, " + _PEDIDO
PEDIDOS_SIM = {VERSAO: PEDIR_SIM, VERSAO_DEPOIS_C6: PEDIR_SIM_DEPOIS_C6}
PEDIR_CPF = "Obrigado! Me envie o seu CPF, só os números, para eu fazer a consulta."
CPF_INVALIDO = "Não consegui ler esse CPF. Envie os 11 números, por favor."
CONSULTANDO = (
    "Pronto, estou consultando. Isso pode levar alguns minutos; assim que tiver "
    "o resultado eu te aviso por aqui."
)

NOMES = {
    "novo": "Empréstimo novo",
    "refin": "Refinanciamento",
    "port": "Portabilidade",
    "port_refin": "Portabilidade com refinanciamento",
}

# TODO(icred): a oferta tem seguro? Onde aparecem o valor e o CET? Até a
# operação responder, a oferta não cita seguro (regra 7, decisão 0027).


def _linha(contrato: dict[str, Any]) -> str:
    nome = NOMES[contrato["tipo"]]
    if contrato.get("banco"):
        nome = f"{nome} ({contrato['banco']})"
    taxa = f"{Decimal(contrato['taxa']):.2f}".replace(".", ",")
    return (
        f"• {nome}: R$ {reais(Decimal(contrato['liberado']))} na sua conta, "
        f"{contrato['prazo']} parcelas de R$ {reais(Decimal(contrato['parcela']))}, "
        f"taxa de {taxa}% ao mês"
    )


def oferta(contratos: list[dict[str, Any]]) -> str:
    """O pacote inteiro: o iCred contrata todos os contratos juntos."""

    partes = ["Consultei o iCred e ele tem esta proposta para você:", ""]
    partes += [_linha(c) for c in contratos]
    if len(contratos) > 1:
        partes += ["", f"Total na sua conta: R$ {reais(total_na_conta(contratos))}."]
        partes.append("A proposta vale para todos os contratos juntos.")
    if eh_estimativa(contratos):
        partes.append(
            "Os valores da portabilidade são uma estimativa e podem mudar quando o "
            "banco confirmar o saldo do contrato."
        )
    partes += ["", "Quer seguir com essa proposta? Responda *SIM* ou *NÃO*."]
    return "\n".join(partes)
