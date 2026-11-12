"""Máscaras de dado pessoal para o painel. Revelar sem máscara exige auditoria."""

from __future__ import annotations

import re


def _digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def mascarar_cpf(cpf: str) -> str:
    digitos = _digitos(cpf)
    return f"***.***.***-{digitos[-2:]}" if len(digitos) == 11 else "***"


def mascarar_telefone(telefone: str) -> str:
    digitos = _digitos(telefone)
    if len(digitos) < 6:
        return "***"
    return f"({digitos[:2]}) *****-{digitos[-4:]}"


def mascarar_data(data: str) -> str:
    """`1990-05-15` → `**/**/1990`: o ano basta para conferir a idade."""

    return f"**/**/{data[:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data) else "***"


def mascarar_email(email: str) -> str:
    """`fulana@exemplo.com` → `f***@exemplo.com`: o domínio ajuda a conferir."""

    usuario, arroba, dominio = email.partition("@")
    return f"{usuario[:1]}***@{dominio}" if arroba and usuario and dominio else "***"


MASCARAS = {
    "cpf": mascarar_cpf,
    "email": mascarar_email,
    "telefone": mascarar_telefone,
    "data_nascimento": mascarar_data,
}
