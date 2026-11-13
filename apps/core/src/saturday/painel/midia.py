"""O que o painel aceita enviar como anexo: lista fechada de tipos e limites.

Os limites seguem os da Meta (imagem 5 MB, áudio 16 MB); documento fica em
16 MB porque o corpo da requisição já para em 20 MB (`web/limites.py`).
"""

from __future__ import annotations

from typing import Literal

Tipo = Literal["imagem", "documento", "audio"]

MB = 1024 * 1024

TIPOS: dict[str, Tipo] = {
    "image/jpeg": "imagem",
    "image/png": "imagem",
    "application/pdf": "documento",
    "audio/webm": "audio",
    "audio/ogg": "audio",
    "audio/mp4": "audio",
    "audio/mpeg": "audio",
}
LIMITE: dict[Tipo, int] = {"imagem": 5 * MB, "documento": 16 * MB, "audio": 16 * MB}
EXTENSAO = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
}


class MidiaRecusada(Exception):
    """O arquivo não pode ser enviado; ``status`` é o HTTP da recusa."""

    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


ROTULO: dict[Tipo, str] = {"imagem": "imagem", "documento": "documento", "audio": "áudio"}

# Assinatura dos primeiros bytes: um .exe renomeado para .pdf não passa.
ASSINATURA = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


def mime_base(content_type: str) -> str:
    """`audio/webm;codecs=opus` → `audio/webm`."""

    return content_type.split(";", 1)[0].strip().lower()


def conferir(dados: bytes, mime_type: str) -> Tipo:
    """Devolve o tipo do anexo ou recusa (415 tipo, 413 tamanho, 422 vazio)."""

    tipo = TIPOS.get(mime_type)
    if tipo is None:
        raise MidiaRecusada(415, "tipo de arquivo não aceito: envie JPG, PNG, PDF ou áudio")
    if not dados:
        raise MidiaRecusada(422, "arquivo vazio")
    if len(dados) > LIMITE[tipo]:
        raise MidiaRecusada(413, f"arquivo grande demais: até {LIMITE[tipo] // MB} MB")
    assinaturas = ASSINATURA.get(mime_type)
    if assinaturas and not dados.startswith(assinaturas):
        raise MidiaRecusada(415, "o conteúdo não bate com o tipo do arquivo")
    return tipo
