"""Cliente da WhatsApp Cloud API (Graph).

Quem entrega é o worker, pelo outbox. Este cliente só sabe falar com a Meta e
classificar o que deu errado: erro temporário vale nova tentativa, erro
permanente não.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from saturday.canais.whatsapp.modelos import IDIOMA, Modelo, componentes
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Códigos que a Meta documenta como transitórios. Vale insistir neles.
CODIGOS_TEMPORARIOS = frozenset({1, 2, 4, 80007, 130429, 131000, 131016, 131048, 131056, 133004})

# Códigos que significam "o texto não pode": fora da janela, template inválido.
CODIGO_JANELA_FECHADA = 131047


class ErroWhatsApp(Exception):
    """Falha ao falar com a Meta."""

    def __init__(self, mensagem: str, *, codigo: int | None = None) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


class ErroTemporario(ErroWhatsApp):
    """5xx, timeout ou código transitório: o outbox deve tentar de novo."""


class ErroPermanente(ErroWhatsApp):
    """4xx de conteúdo ou credencial: repetir não resolve."""


def _codigo_da_resposta(corpo: dict[str, Any]) -> int | None:
    erro = corpo.get("error")
    if isinstance(erro, dict):
        codigo = erro.get("code")
        if isinstance(codigo, int):
            return codigo
    return None


def classificar(status: int, corpo: dict[str, Any]) -> ErroWhatsApp:
    """Traduz a resposta em erro temporário ou permanente."""

    codigo = _codigo_da_resposta(corpo)
    detalhe = f"status={status} codigo={codigo}"
    if status >= 500 or codigo in CODIGOS_TEMPORARIOS:
        return ErroTemporario(detalhe, codigo=codigo)
    return ErroPermanente(detalhe, codigo=codigo)


class WhatsAppClient:
    """Envio e leitura de mídia. Não decide *o que* enviar."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._base = settings.whatsapp_graph_url.rstrip("/")
        self._token = settings.whatsapp_token.get_secret_value()
        self._limite_midia = settings.whatsapp_limite_midia_mb * 1024 * 1024

    def _cabecalhos(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _enviar(self, phone_number_id: str, corpo: dict[str, Any]) -> str | None:
        """POST em `/{phone_number_id}/messages`; devolve o `wamid`."""

        url = f"{self._base}/{phone_number_id}/messages"
        try:
            resposta = self._http.post(url, json=corpo, headers=self._cabecalhos())
        except httpx.HTTPError as exc:
            raise ErroTemporario(f"rede: {type(exc).__name__}") from exc

        try:
            dados = resposta.json()
        except ValueError:
            dados = {}

        if resposta.status_code >= 400:
            erro = classificar(resposta.status_code, dados)
            logger.warning(
                "whatsapp_envio_falhou status=%s codigo=%s tipo=%s",
                resposta.status_code,
                erro.codigo,
                type(erro).__name__,
            )
            raise erro

        mensagens = dados.get("messages")
        if isinstance(mensagens, list) and mensagens:
            primeira = mensagens[0]
            if isinstance(primeira, dict):
                wamid = primeira.get("id")
                if isinstance(wamid, str):
                    return wamid
        return None

    def enviar_texto(self, phone_number_id: str, numero: str, texto: str) -> str | None:
        return self._enviar(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": numero,
                "type": "text",
                "text": {"preview_url": False, "body": texto},
            },
        )

    def enviar_modelo(
        self,
        phone_number_id: str,
        numero: str,
        modelo: Modelo,
        *,
        parametros: list[str] | None = None,
        sufixo_link: str | None = None,
    ) -> str | None:
        template: dict[str, Any] = {
            "name": modelo.nome,
            "language": {"code": IDIOMA},
        }
        partes = componentes(parametros or [], sufixo_link=sufixo_link)
        if partes:
            template["components"] = partes

        return self._enviar(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": numero,
                "type": "template",
                "template": template,
            },
        )

    def marcar_lida(self, phone_number_id: str, wamid: str) -> None:
        """Marca como lida. Falhar aqui não pode derrubar o processamento."""

        try:
            self._http.post(
                f"{self._base}/{phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": wamid,
                },
                headers=self._cabecalhos(),
            )
        except httpx.HTTPError as exc:
            logger.info("whatsapp_marcar_lida_falhou erro=%s", type(exc).__name__)

    def baixar_midia(self, media_id: str) -> tuple[bytes, str]:
        """Dois passos: metadados no Graph, bytes na URL devolvida.

        A URL de mídia da Meta fica em outro host (`lookaside.fbsbx.com`), então
        ela não passa pela lista de domínios permitidos dos anexos: a origem é
        o próprio `media_id` que veio no webhook assinado.
        """

        try:
            meta = self._http.get(f"{self._base}/{media_id}", headers=self._cabecalhos())
            meta.raise_for_status()
        except httpx.HTTPError as exc:
            raise ErroTemporario(f"midia_metadados: {type(exc).__name__}") from exc

        dados = meta.json()
        url = dados.get("url")
        mime = dados.get("mime_type") or "application/octet-stream"
        if not isinstance(url, str):
            raise ErroPermanente("midia_sem_url")

        partes: list[bytes] = []
        total = 0
        try:
            with self._http.stream("GET", url, headers=self._cabecalhos()) as resposta:
                resposta.raise_for_status()
                for pedaco in resposta.iter_bytes():
                    total += len(pedaco)
                    if total > self._limite_midia:
                        raise ErroPermanente("midia_acima_do_limite")
                    partes.append(pedaco)
        except httpx.HTTPError as exc:
            raise ErroTemporario(f"midia_download: {type(exc).__name__}") from exc

        return b"".join(partes), str(mime)
