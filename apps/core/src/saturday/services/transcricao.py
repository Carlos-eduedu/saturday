"""Transcrição de áudio.

Endpoint compatível com o da OpenAI (`POST {base}/audio/transcriptions`,
multipart com `model` e `file`, resposta `{"text": ...}`). Sem chave ou modelo
configurado o transcritor fica desligado e o canal pede texto ao cliente.
"""

from __future__ import annotations

import logging

import httpx

from saturday.settings import Settings

logger = logging.getLogger(__name__)

EXTENSAO_POR_MIME = {
    "audio/ogg": "ogg",
    "audio/ogg; codecs=opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "audio/wav": "wav",
}


class Transcritor:
    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._base = settings.transcricao_base_url.rstrip("/")
        self._chave = settings.transcricao_api_key.get_secret_value()
        self._modelo = settings.transcricao_modelo

    @property
    def habilitado(self) -> bool:
        return bool(self._chave and self._modelo)

    def transcrever(self, dados: bytes, mime_type: str) -> str | None:
        """Devolve o texto, ou ``None`` quando não deu para transcrever."""

        if not self.habilitado:
            return None

        extensao = EXTENSAO_POR_MIME.get(mime_type, "ogg")
        arquivos = {"file": (f"audio.{extensao}", dados, mime_type or "audio/ogg")}
        try:
            resposta = self._http.post(
                f"{self._base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._chave}"},
                data={"model": self._modelo, "language": "pt"},
                files=arquivos,
            )
        except httpx.HTTPError as exc:
            logger.warning("transcricao_falhou erro=%s", type(exc).__name__)
            return None

        if resposta.status_code >= 400:
            logger.warning("transcricao_falhou status=%s", resposta.status_code)
            return None

        try:
            corpo = resposta.json()
        except ValueError:
            return None
        if not isinstance(corpo, dict):
            return None
        texto = corpo.get("text")
        if not isinstance(texto, str) or not texto.strip():
            return None
        return texto.strip()
