"""Leitura determinística das respostas do cliente no ramo CLT.

Cada função recebe o texto livre e devolve o valor reconhecido ou ``None``. Não
há LLM aqui: triagem, identificação e consentimento são decisões em código
(AGENTS.md, regra 2).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from saturday.agent.coleta import parse_data_nascimento
from saturday.bancos.granatech.numeros import decimal_ou_none

# `re` não tem `\p{L}`; `[^\W\d_]` é "letra" em Unicode.
_LETRA = r"[^\W\d_]"
SIM_CONSENTIMENTO = re.compile(rf"(^|(?!{_LETRA}).)(sim|autorizo|aceito)((?!{_LETRA}).|$)", re.I)
NEGACAO = re.compile(rf"(^|(?!{_LETRA}).)(não|nao|nunca|jamais)((?!{_LETRA}).|$)", re.I)

_AFIRMATIVAS = frozenset(
    {"sim", "s", "ss", "isso", "claro", "certo", "tenho", "trabalho", "sou", "estou", "tem"}
)
_NEGATIVAS = frozenset({"nao", "n", "nunca", "nenhum", "nenhuma", "negativo", "jamais"})
_DUVIDA = ("nao sei", "sei la", "talvez", "acho que")
_ACEITE = frozenset({"quero", "aceito", "bora", "vamos", "pode", "fechado", "topo"})
_NUMEROS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
}


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaços simples."""

    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _palavras(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalizar(texto))


def _digitos(texto: str) -> str | None:
    """Só dígitos, se o texto for só número com pontuação de documento."""

    if not re.fullmatch(r"[\d\s.\-/()+]+", texto.strip()):
        return None
    return re.sub(r"\D", "", texto)


def eh_pergunta(texto: str) -> bool:
    return "?" in texto


# ---------------------------------------------------------------- sim/não


def sim_ou_nao(texto: str) -> bool | None:
    normal = normalizar(texto)
    if any(trecho in normal for trecho in _DUVIDA):
        return None
    palavras = set(_palavras(texto))
    nega = bool(palavras & _NEGATIVAS)
    afirma = "sim" in palavras or (not nega and bool(palavras & _AFIRMATIVAS))
    if nega and afirma:
        return None
    if nega:
        return False
    return True if afirma else None


def aceitou(texto: str) -> bool:
    """Resposta à oferta: um sim (ou "quero", "aceito"...) sem negação."""

    palavras = set(_palavras(texto))
    if palavras & _NEGATIVAS:
        return False
    return "sim" in palavras or bool(palavras & _ACEITE)


def consentiu(texto: str) -> bool:
    """Regra do SIM do contrato: sim/autorizo/aceito como palavra, sem negação."""

    return bool(SIM_CONSENTIMENTO.search(texto)) and not NEGACAO.search(texto)


# ---------------------------------------------------------------- triagem


def tempo_de_casa_meses(texto: str) -> int | None:
    """``"2 anos"`` → 24, ``"1 ano e meio"`` → 18, ``"8 meses"`` → 8."""

    normal = normalizar(texto)
    for palavra, numero in _NUMEROS.items():
        normal = re.sub(rf"\b{palavra}\b", str(numero), normal)
    if re.search(r"\bmeio ano\b", normal):
        return 6
    anos = re.search(r"(\d+)\s*anos?\b", normal)
    meses = re.search(r"(\d+)\s*m[e]s(es)?\b", normal)
    if not anos and not meses:
        return None
    total = 0
    if anos:
        total += int(anos.group(1)) * 12
        if re.search(r"anos?\s+e\s+meio\b", normal):
            total += 6
    if meses:
        total += int(meses.group(1))
    return total


# ---------------------------------------------------------------- documentos


def _dv_cpf(digitos: str) -> bool:
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        if (soma * 10 % 11) % 10 != int(digitos[tamanho]):
            return False
    return True


def cpf(texto: str) -> str | None:
    digitos = _digitos(texto)
    if not digitos or len(digitos) != 11 or len(set(digitos)) == 1:
        return None
    return digitos if _dv_cpf(digitos) else None


def _dv_cnpj(digitos: str) -> bool:
    for tamanho in (12, 13):
        pesos = [*range(tamanho - 7, 1, -1), *range(9, 1, -1)]
        soma = sum(int(d) * p for d, p in zip(digitos[:tamanho], pesos, strict=True))
        resto = soma % 11
        if (0 if resto < 2 else 11 - resto) != int(digitos[tamanho]):
            return False
    return True


def cnpj(texto: str) -> str | None:
    digitos = _digitos(texto)
    if not digitos or len(digitos) != 14 or len(set(digitos)) == 1:
        return None
    return digitos if _dv_cnpj(digitos) else None


# ---------------------------------------------------------------- identificação


def nome_completo(texto: str) -> str | None:
    partes = texto.split()
    if len(partes) < 2:
        return None
    if not all(re.fullmatch(rf"{_LETRA}+(['-]{_LETRA}+)*", p) for p in partes):
        return None
    if sum(len(p) >= 2 for p in partes) < 2:
        return None
    return " ".join(partes)


def data_nascimento(texto: str, hoje: date) -> date | None:
    lida = parse_data_nascimento(texto, hoje)
    return date.fromisoformat(lida[0]) if lida else None


def sexo(texto: str) -> str | None:
    palavras = set(_palavras(texto))
    feminino = bool(palavras & {"f", "feminino", "mulher", "fem"})
    masculino = bool(palavras & {"m", "masculino", "homem", "masc"})
    if feminino == masculino:
        return None
    return "F" if feminino else "M"


def email(texto: str) -> str | None:
    valor = texto.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", valor):
        return None
    return valor


def celular(texto: str) -> str | None:
    """Celular com DDD, 11 dígitos, nono dígito 9; aceita o 55 na frente."""

    digitos = _digitos(texto)
    if not digitos:
        return None
    if len(digitos) == 13 and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) != 11 or digitos[2] != "9" or digitos[0] == "0":
        return None
    return digitos


# ---------------------------------------------------------------- vínculo e oferta


def numero_da_lista(texto: str, quantidade: int) -> int | None:
    """Índice (base 0) da opção escolhida numa lista numerada de 1 a ``quantidade``."""

    achados = re.findall(r"\d+", texto)
    if len(achados) != 1:
        return None
    numero = int(achados[0])
    return numero - 1 if 1 <= numero <= quantidade else None


@dataclass(frozen=True)
class Pedido:
    """Mudança pedida pelo cliente depois da oferta."""

    sem_seguro: bool = False
    parcelas: int | None = None
    valor_parcela: Decimal | None = None


def pedido_de_mudanca(texto: str) -> Pedido | None:
    normal = normalizar(texto)
    sem_seguro = bool(
        re.search(r"\bsem (o )?seguro\b|\b(tira|tirar|retira|retirar) (o )?seguro\b", normal)
        or re.search(r"\bnao quero (o )?seguro\b", normal)
    )
    parcelas = None
    achado = re.search(r"\b(\d{1,2})\s*(x|vezes|parcelas|meses)\b", normal)
    if achado:
        parcelas = int(achado.group(1))
    valor = None
    achado = re.search(r"(?:r\$|parcela de|parcelas de)\s*r?\$?\s*(\d[\d.,]*)", normal)
    if achado:
        valor = decimal_ou_none(achado.group(1).rstrip(".,"))
    if not sem_seguro and parcelas is None and valor is None:
        return None
    return Pedido(sem_seguro=sem_seguro, parcelas=parcelas, valor_parcela=valor)
