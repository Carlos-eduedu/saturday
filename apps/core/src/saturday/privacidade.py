"""Máscaras de dado pessoal para o painel e os logs. Revelar sem máscara exige auditoria."""

from __future__ import annotations

import re
from typing import Any

from saturday.canais.base import CANAIS_WHATSAPP


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


def mascarar_conversation_id(conversation_id: str) -> str:
    """O `conversation_id` como vai para o log (regra 9).

    `whatsapp:11987654321` → `whatsapp:(11) *****-4321`. O id do `POST /chat` é
    de quem integra e passa como veio, a não ser que traga uma sequência com
    cara de telefone (10 dígitos ou mais, isolados).
    """

    canal, separador, resto = conversation_id.partition(":")
    # `canal:telefone`, montado por `prefixo_do_canal`.
    if separador and canal in CANAIS_WHATSAPP:
        return f"{canal}:{mascarar_telefone(resto)}"
    # Sequência isolada: dígitos no meio de um id hexadecimal não são telefone.
    return re.sub(
        r"(?<![A-Za-z0-9])\d{10,}(?![A-Za-z0-9])",
        lambda achado: mascarar_telefone(achado.group()),
        conversation_id,
    )


MASCARAS = {
    "cpf": mascarar_cpf,
    "email": mascarar_email,
    "telefone": mascarar_telefone,
    "data_nascimento": mascarar_data,
}


# Onde a Granatech põe o CPF: `cpf` (listas, propostas) e `pessoa_natural.document`.
_CHAVES_DE_DOCUMENTO = {"document", "documento"}


def mascarar_cpfs(corpo: Any) -> Any:
    """CPF mascarado em qualquer nível de um JSON da Granatech (proxy e aviso, decisão 0035)."""

    if isinstance(corpo, list):
        return [mascarar_cpfs(item) for item in corpo]
    if not isinstance(corpo, dict):
        return corpo
    return {
        chave: mascarar_cpf(valor)
        if isinstance(valor, str) and ("cpf" in chave.lower() or chave in _CHAVES_DE_DOCUMENTO)
        else mascarar_cpfs(valor)
        for chave, valor in corpo.items()
    }
