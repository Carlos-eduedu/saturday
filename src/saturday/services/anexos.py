"""Download e decodificação dos anexos recebidos pela API."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

import httpx

from saturday.settings import ANEXO_MAX_MB, ANEXO_TIMEOUT_S, MIME_ACEITOS, Settings

LIMITE_BYTES = ANEXO_MAX_MB * 1024 * 1024


class AnexoInvalido(ValueError):
    """Anexo com MIME, origem ou tamanho inválido."""


@dataclass(frozen=True)
class Anexo:
    mime_type: str
    data: bytes

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64}"


def _normalizar_mime(mime: object) -> str:
    if not isinstance(mime, str):
        raise AnexoInvalido("mime_type ausente")
    mime = mime.split(";", 1)[0].strip().lower()
    if mime not in MIME_ACEITOS:
        raise AnexoInvalido("mime_type não aceito")
    return mime


def _validar_tamanho(data: bytes) -> bytes:
    if not data:
        raise AnexoInvalido("anexo vazio")
    if len(data) > LIMITE_BYTES:
        raise AnexoInvalido("anexo acima do limite")
    return data


def _decodificar_base64(valor: str) -> bytes:
    texto = "".join(valor.split())
    if texto.startswith("data:"):
        _, _, texto = texto.partition(",")
    try:
        data = base64.b64decode(texto, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AnexoInvalido("base64 inválido") from exc
    return _validar_tamanho(data)


def mensagem_anexo_invalido() -> str:
    return (
        "Não consegui abrir esse arquivo. Envie o extrato de empréstimos do "
        "Meu INSS em PDF ou como foto (JPG, PNG ou WEBP), com até "
        f"{ANEXO_MAX_MB} MB."
    )


class AnexosClient:
    """Baixa/decodifica anexos usando o cliente HTTP compartilhado."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._settings = settings

    def _baixar(self, url: str) -> bytes:
        try:
            response = self._http.get(
                url,
                timeout=ANEXO_TIMEOUT_S,
                follow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:
            raise AnexoInvalido("falha ao baixar anexo") from exc
        return _validar_tamanho(response.content)

    def carregar_anexo(self, item: dict[str, Any]) -> Anexo:
        mime = _normalizar_mime(item.get("mime_type"))
        url = item.get("url")
        base64_valor = item.get("base64")

        if bool(url) == bool(base64_valor):
            raise AnexoInvalido("anexo deve ter url ou base64")
        data = self._baixar(str(url)) if url else _decodificar_base64(str(base64_valor))
        return Anexo(mime_type=mime, data=data)

    def carregar_anexos(self, itens: list[dict[str, Any]]) -> list[Anexo]:
        if not itens:
            raise AnexoInvalido("nenhum anexo")
        return [self.carregar_anexo(item) for item in itens]

    def mensagem_anexo_invalido(self) -> str:
        return mensagem_anexo_invalido()
