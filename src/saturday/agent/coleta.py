"""Validação dos dados coletados do cliente (data de nascimento e UF)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from saturday.portabilidade import calculo
from saturday.portabilidade.regras import IDADE_COLETA_MAX, IDADE_COLETA_MIN
from saturday.settings import TZ_OPERACAO

UFS_POR_NOME = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}
SIGLAS_UF = frozenset(UFS_POR_NOME.values())
PADRAO_DATA_NASCIMENTO = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def hoje_operacao() -> date:
    return datetime.now(ZoneInfo(TZ_OPERACAO)).date()


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


def normalizar_uf(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not texto:
        return None
    sigla = texto.upper()
    if sigla in SIGLAS_UF:
        return sigla
    return UFS_POR_NOME.get(_sem_acento(texto))


def parse_data_nascimento(texto: str, hoje: date) -> tuple[str, int] | None:
    """Devolve (ISO, idade) ou ``None`` se a data não for válida para coleta."""

    match = PADRAO_DATA_NASCIMENTO.fullmatch(texto.strip())
    if not match:
        return None
    dia, mes, ano_texto = match.groups()
    ano = int(ano_texto)
    if len(ano_texto) == 2:
        seculo = hoje.year - hoje.year % 100
        ano = seculo + ano
        if ano > hoje.year:
            ano -= 100
    try:
        nascimento = date(ano, int(mes), int(dia))
    except ValueError:
        return None

    idade = calculo.idade_em_anos(nascimento, hoje)
    if idade is None or idade < IDADE_COLETA_MIN or idade > IDADE_COLETA_MAX:
        return None
    return nascimento.isoformat(), idade


def texto_valido_para(aguardando: str | None, texto: str, hoje: date) -> bool:
    if aguardando == "data_nascimento":
        return parse_data_nascimento(texto, hoje) is not None
    if aguardando == "uf":
        return normalizar_uf(texto) is not None
    return False
