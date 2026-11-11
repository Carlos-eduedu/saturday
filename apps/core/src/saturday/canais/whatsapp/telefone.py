"""Normalização do telefone que chega pelo WhatsApp.

A Meta manda o `wa_id` no formato internacional, sem o `+`. O resto do sistema
trabalha com DDD + número, no formato que o cliente digita aqui no Brasil.
"""

from __future__ import annotations

DDD_BRASIL = "55"
# Celulares têm o nono dígito; o primeiro dígito do assinante fica entre 6 e 9.
PRIMEIROS_DIGITOS_CELULAR = frozenset("6789")


def normalizar_telefone(bruto: str) -> str:
    """Devolve DDD + número, sem o código do país.

    ``5511987654321`` vira ``11987654321``. Um número antigo de 10 dígitos
    (``551187654321``) recebe o nono dígito: ``11987654321``. Números que não
    são celulares ficam com 10 dígitos, porque o nono dígito não existe neles.
    """

    digitos = "".join(caractere for caractere in bruto if caractere.isdigit())
    if digitos.startswith(DDD_BRASIL) and len(digitos) in {12, 13}:
        digitos = digitos[len(DDD_BRASIL) :]

    if len(digitos) == 10 and digitos[2] in PRIMEIROS_DIGITOS_CELULAR:
        digitos = f"{digitos[:2]}9{digitos[2:]}"

    return digitos


def phone_number_id_de(evento: dict[str, object]) -> str:
    """`phone_number_id` do metadado do webhook, como texto."""

    metadados = evento.get("metadata")
    if isinstance(metadados, dict):
        valor = metadados.get("phone_number_id")
        if isinstance(valor, str):
            return valor
    return ""
