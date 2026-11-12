"""Cliente HTTP da Evolution API (v2.3.7).

Só as rotas da decisão 0009: envio de texto e download de mídia. Os erros
seguem a hierarquia do WhatsApp da Meta, porque a saída e a entrada já sabem
classificá-los; repetir é só do outbox (decisão 0001).
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

import httpx

from saturday.canais.whatsapp.cliente import (
    ErroIncerto,
    ErroPermanente,
    ErroTemporario,
    ErroWhatsApp,
)
from saturday.settings import Settings

logger = logging.getLogger(__name__)

DDI_BRASIL = "55"


def _numero_inexistente(corpo: dict[str, Any]) -> bool:
    """400 com `[{exists: false}]`: o número não tem WhatsApp."""

    resposta = corpo.get("response")
    mensagens = resposta.get("message") if isinstance(resposta, dict) else None
    return isinstance(mensagens, list) and any(
        isinstance(item, dict) and item.get("exists") is False for item in mensagens
    )


def classificar(status: int, corpo: dict[str, Any]) -> ErroWhatsApp:
    """O que a resposta de erro diz sobre tentar de novo.

    Outros 400 cobrem a instância desconectada ("Connection Closed"), que volta
    quando o número for reconectado; credencial e instância errada não voltam.
    """

    detalhe = f"evolution status={status}"
    if status >= 500:
        return ErroTemporario(detalhe)
    if status == 400 and not _numero_inexistente(corpo):
        return ErroTemporario(detalhe)
    return ErroPermanente(detalhe)


class EvolutionClient:
    """Envio e leitura de mídia. Não decide *o que* enviar."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._base = settings.evolution_url.rstrip("/")
        self._chave = settings.evolution_api_key.get_secret_value()
        self._limite_midia = settings.whatsapp_limite_midia_mb * 1024 * 1024

    def _post(self, rota: str, corpo: dict[str, Any]) -> dict[str, Any]:
        try:
            resposta = self._http.post(
                f"{self._base}{rota}", json=corpo, headers={"apikey": self._chave}
            )
        except (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            # A conexão caiu depois do envio: não dá para saber se saiu.
            raise ErroIncerto(f"leitura: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise ErroTemporario(f"rede: {type(exc).__name__}") from exc

        try:
            dados = resposta.json()
        except ValueError:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}

        if resposta.status_code >= 400:
            erro = classificar(resposta.status_code, dados)
            logger.warning(
                "evolution_falhou rota=%s status=%s tipo=%s",
                rota.split("/")[1],
                resposta.status_code,
                type(erro).__name__,
            )
            raise erro
        return dados

    def enviar_texto(self, instancia: str, numero: str, texto: str) -> str | None:
        """Devolve o id da mensagem (`key.id`), que os status usam."""

        dados = self._post(
            f"/message/sendText/{instancia}",
            {"number": f"{DDI_BRASIL}{numero}", "text": texto},
        )
        chave = dados.get("key")
        if isinstance(chave, dict) and isinstance(chave.get("id"), str):
            return str(chave["id"])
        return None

    def marcar_lida(self, instancia: str, wamid: str) -> None:
        """Nada a fazer: a instância lê sozinho (`readMessages=true`).

        A rota de leitura pede o JID do cliente, que a entrada não guarda; a
        configuração da instância faz o mesmo sem uma chamada a mais.
        """

    def baixar_midia(self, media_id: str, instancia: str) -> tuple[bytes, str]:
        """A Evolution acha a mídia pelo id na base dela e devolve em base64.

        Exige `DATABASE_SAVE_DATA_NEW_MESSAGE=true` na instância.
        """

        dados = self._post(
            f"/chat/getBase64FromMediaMessage/{instancia}",
            {"message": {"key": {"id": media_id}}},
        )
        codificado = dados.get("base64")
        if not isinstance(codificado, str) or not codificado:
            raise ErroPermanente("midia_sem_conteudo")
        # base64 ocupa 4/3 do arquivo: confere antes de decodificar.
        if len(codificado) * 3 // 4 > self._limite_midia:
            raise ErroPermanente("midia_acima_do_limite")
        try:
            conteudo = base64.b64decode(codificado, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ErroPermanente("midia_base64_invalido") from exc
        return conteudo, str(dados.get("mimetype") or "application/octet-stream")
