"""Download e decodificação dos anexos recebidos pela API."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from saturday.metrics import registrar_chamada
from saturday.settings import ANEXO_MAX_MB, ANEXO_TIMEOUT_S, MIME_ACEITOS, Settings
from saturday.storage.base import Storage

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

    def __init__(
        self,
        http: httpx.Client,
        settings: Settings,
        storage: Storage | None = None,
    ) -> None:
        self._http = http
        self._settings = settings
        self._storage = storage

    def _validar_host(self, host: str) -> None:
        host = host.strip().lower().rstrip(".")
        dominios = [
            dominio.strip().lower().lstrip(".")
            for dominio in self._settings.anexo_dominios
            if dominio.strip()
        ]
        if not dominios or not any(
            host == dominio or host.endswith("." + dominio) for dominio in dominios
        ):
            raise AnexoInvalido("domínio de anexo não permitido")

        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise AnexoInvalido("host do anexo não resolve") from exc

        for info in infos:
            endereco = info[4][0]
            try:
                ip = ipaddress.ip_address(endereco)
            except ValueError as exc:
                raise AnexoInvalido("endereço de anexo inválido") from exc
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
                or not ip.is_global
            ):
                raise AnexoInvalido("endereço de anexo não permitido")

    def _validar_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise AnexoInvalido("anexo por URL exige HTTPS")
        self._validar_host(parsed.hostname)

    def _baixar(self, url: str) -> bytes:
        inicio = time.monotonic()
        try:
            self._validar_url(url)
            with self._http.stream(
                "GET",
                url,
                timeout=ANEXO_TIMEOUT_S,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise AnexoInvalido("redirecionamento de anexo não permitido")
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        tamanho = int(content_length)
                    except ValueError:
                        tamanho = 0
                    if tamanho > LIMITE_BYTES:
                        raise AnexoInvalido("anexo acima do limite")

                dados = bytearray()
                for parte in response.iter_bytes():
                    dados.extend(parte)
                    if len(dados) > LIMITE_BYTES:
                        raise AnexoInvalido("anexo acima do limite")
        except AnexoInvalido:
            raise
        except Exception as exc:
            raise AnexoInvalido("falha ao baixar anexo") from exc
        finally:
            registrar_chamada("anexo", (time.monotonic() - inicio) * 1000)

        return _validar_tamanho(bytes(dados))

    def carregar_anexo(self, item: dict[str, Any]) -> Anexo:
        mime = _normalizar_mime(item.get("mime_type"))
        url = item.get("url")
        base64_valor = item.get("base64")
        chave = item.get("chave")

        origens = [url, base64_valor, chave]
        if sum(origem is not None for origem in origens) != 1:
            raise AnexoInvalido("anexo deve ter url, base64 ou chave")

        if chave:
            if self._storage is None:
                raise AnexoInvalido("anexo arquivado sem storage configurado")
            try:
                data = self._storage.ler(str(chave))
            except KeyError as exc:
                raise AnexoInvalido("anexo não encontrado no storage") from exc
        elif url:
            data = self._baixar(str(url))
        else:
            data = _decodificar_base64(str(base64_valor))

        return Anexo(mime_type=mime, data=data)

    def carregar_anexos(self, itens: list[dict[str, Any]]) -> list[Anexo]:
        if not itens:
            raise AnexoInvalido("nenhum anexo")
        return [self.carregar_anexo(item) for item in itens]

    def mensagem_anexo_invalido(self) -> str:
        return mensagem_anexo_invalido()
