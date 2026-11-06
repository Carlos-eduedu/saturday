"""Schema, normalização e conferência do extrato Hiscon."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from saturday.portabilidade.regras import TOLERANCIA_CONFERENCIA
from saturday.settings import TZ_OPERACAO

STATUS_OK = "ok"
STATUS_NAO_HISCON = "nao_hiscon"
STATUS_ILEGIVEL = "ilegivel"
STATUS_MES_ERRADO = "mes_errado"
STATUS_CONFERENCIA_FALHOU = "hiscon_nao_conferiu"
STATUS_ESPECIE_NAO_ATENDIDA = "especie_nao_atendida"


class ExtratoInvalido(ValueError):
    """JSON que não pôde ser interpretado como extrato."""


def numero_brasileiro(valor: Any) -> float | None:
    """Converte "1.234,56" em 1234.56. Inválido vira None, nunca zero."""

    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if not isinstance(valor, str):
        return None

    texto = valor.strip().replace("R$", "").replace("%", "").replace("\u00a0", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _inteiro(valor: Any) -> int | None:
    numero = numero_brasileiro(valor)
    if numero is None or not float(numero).is_integer():
        return None
    return int(numero)


def _booleano(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return valor != 0
    if isinstance(valor, str):
        return valor.strip().lower() in {"true", "sim", "s", "1", "yes"}
    return False


def _normalizar_data_br(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).strftime("%d/%m/%Y")
        except ValueError:
            continue
    try:
        return datetime.strptime(texto, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def _normalizar_inicio(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", texto)
    if match:
        return f"{int(match.group(1)):02d}/{match.group(2)}"
    return texto


def _normalizar_banco(valor: Any) -> tuple[str, str]:
    texto = str(valor or "").strip()
    if not texto:
        return "", ""
    codigo = ""
    nome = texto
    match = re.match(r"^\s*(\d{1,6})\s*[-–—]\s*(.*)$", texto)
    if match:
        codigo = match.group(1).zfill(3)
        nome = match.group(2).strip()
    else:
        match = re.match(r"^\s*(\d{1,6})\s*$", texto)
        if match:
            codigo = match.group(1).zfill(3)
            nome = ""
    banco = f"{codigo} - {nome}" if codigo and nome else (codigo or texto)
    return banco, codigo


def _parse_data(valor: Any) -> date | None:
    if not isinstance(valor, str):
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor.strip(), formato).date()
        except ValueError:
            continue
    return None


def _inicio_valido(valor: Any) -> bool:
    if not isinstance(valor, str):
        return False
    try:
        datetime.strptime(valor.strip(), "%m/%Y")
        return True
    except ValueError:
        return False


def _ativo(situacao: Any) -> bool:
    return isinstance(situacao, str) and situacao.strip().lower().startswith("ativo")


class ContratoHiscon(BaseModel):
    model_config = ConfigDict(extra="ignore")

    banco: str = ""
    banco_codigo: str = ""
    situacao: str = ""
    parcela: float | None = None
    taxaMensal: float | None = None
    qtdParcelas: int | None = None
    inicioDesconto: str | None = None
    dataInclusao: str | None = None
    legivel: bool = False

    @field_validator("banco", mode="before")
    @classmethod
    def _banco(cls, valor: Any) -> str:
        return _normalizar_banco(valor)[0]

    @field_validator("situacao", mode="before")
    @classmethod
    def _situacao(cls, valor: Any) -> str:
        return str(valor) if valor is not None else ""

    @field_validator("parcela", "taxaMensal", mode="before")
    @classmethod
    def _numero(cls, valor: Any) -> float | None:
        return numero_brasileiro(valor)

    @field_validator("qtdParcelas", mode="before")
    @classmethod
    def _qtd(cls, valor: Any) -> int | None:
        return _inteiro(valor)

    @field_validator("inicioDesconto", mode="before")
    @classmethod
    def _inicio(cls, valor: Any) -> str | None:
        return _normalizar_inicio(valor)

    @field_validator("dataInclusao", mode="before")
    @classmethod
    def _inclusao(cls, valor: Any) -> str | None:
        return _normalizar_data_br(valor)


class Extrato(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ehHiscon: bool = False
    especie: str | None = None
    liberadoParaEmprestimo: bool = False
    dataEmissao: str | None = None
    margemUtilizada: float | None = None
    margemDisponivel: float | None = None
    margemReservada: float | None = None
    margemExtrapolada: float | None = None
    contratos: list[ContratoHiscon] = Field(default_factory=list)

    @field_validator("ehHiscon", "liberadoParaEmprestimo", mode="before")
    @classmethod
    def _bool(cls, valor: Any) -> bool:
        return _booleano(valor)

    @field_validator("especie", mode="before")
    @classmethod
    def _especie(cls, valor: Any) -> str | None:
        if valor is None:
            return None
        if (
            isinstance(valor, (int, float))
            and not isinstance(valor, bool)
            and float(valor).is_integer()
        ):
            valor = int(valor)
        digitos = "".join(ch for ch in str(valor) if ch.isdigit())
        return str(int(digitos)) if digitos else None

    @field_validator("dataEmissao", mode="before")
    @classmethod
    def _emissao(cls, valor: Any) -> str | None:
        return _normalizar_data_br(valor)

    @field_validator(
        "margemUtilizada",
        "margemDisponivel",
        "margemReservada",
        "margemExtrapolada",
        mode="before",
    )
    @classmethod
    def _margem(cls, valor: Any) -> float | None:
        return numero_brasileiro(valor)

    def tem_contrato_legivel(self) -> bool:
        return any(c.legivel for c in self.contratos)


def _marcar_legibilidade(extrato: Extrato) -> Extrato:
    for contrato in extrato.contratos:
        contrato.legivel = bool(
            contrato.parcela is not None
            and contrato.parcela > 0
            and contrato.qtdParcelas is not None
            and contrato.qtdParcelas > 0
            and contrato.taxaMensal is not None
            and contrato.taxaMensal > 0
            and _inicio_valido(contrato.inicioDesconto)
        )
        _, codigo = _normalizar_banco(contrato.banco)
        contrato.banco_codigo = codigo
    return extrato


def normalizar_extrato(dados: Any) -> Extrato:
    """Normaliza o JSON cru do modelo para o schema do serviço."""

    if isinstance(dados, (str, bytes)):
        try:
            dados = json.loads(dados)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ExtratoInvalido("extrato não é um JSON válido") from exc
    if hasattr(dados, "model_dump") and not isinstance(dados, dict):
        dados = dados.model_dump()
    if not isinstance(dados, dict):
        raise ExtratoInvalido("extrato não é um objeto")

    base = dict(dados)
    brutos = base.get("contratos")
    contratos: list[ContratoHiscon] = []
    if isinstance(brutos, list):
        for bruto in brutos:
            if isinstance(bruto, dict):
                contratos.append(ContratoHiscon.model_validate(bruto))
    base["contratos"] = contratos
    extrato = Extrato.model_validate(base)
    return _marcar_legibilidade(extrato)


def _garantir_extrato(valor: Any) -> Extrato:
    return valor if isinstance(valor, Extrato) else normalizar_extrato(valor)


def conferir_margem(extrato: Extrato | dict[str, Any]) -> bool:
    extrato = _garantir_extrato(extrato)
    if extrato.margemUtilizada is None or extrato.margemReservada is None:
        return False

    soma = 0.0
    for contrato in extrato.contratos:
        if not _ativo(contrato.situacao):
            continue
        if contrato.parcela is None:
            return False
        soma += contrato.parcela

    return abs(soma + extrato.margemReservada - extrato.margemUtilizada) <= (
        TOLERANCIA_CONFERENCIA + 1e-9
    )


def extrato_do_mes(extrato: Extrato | dict[str, Any], hoje: date | None = None) -> bool:
    extrato = _garantir_extrato(extrato)
    emissao = _parse_data(extrato.dataEmissao)
    if emissao is None:
        return False
    hoje = hoje or datetime.now(ZoneInfo(TZ_OPERACAO)).date()
    return (emissao.year, emissao.month) == (hoje.year, hoje.month)


def validar_extrato(extrato: Extrato | dict[str, Any], hoje: date | None = None) -> str:
    """Aplica a seção 8.2, na ordem, e devolve um status."""

    extrato = _garantir_extrato(extrato)
    if not extrato.ehHiscon:
        return STATUS_NAO_HISCON
    if _parse_data(extrato.dataEmissao) is None or not extrato.tem_contrato_legivel():
        return STATUS_ILEGIVEL
    if not extrato_do_mes(extrato, hoje):
        return STATUS_MES_ERRADO
    if not conferir_margem(extrato):
        return STATUS_CONFERENCIA_FALHOU
    if extrato.especie in {"87", "88"}:
        return STATUS_ESPECIE_NAO_ATENDIDA
    return STATUS_OK


# Nome alternativo, conforme a terminologia do plano.
normalizar_numero = numero_brasileiro
