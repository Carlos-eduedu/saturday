"""Tradução do evento do WhatsApp em um turno do agente.

Baixa a mídia, guarda no storage e resolve o áudio em texto. O que não dá para
aproveitar vira resposta local, sem rodar o grafo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from saturday.agent.textos import mensagem_audio_ilegivel, mensagem_midia_ilegivel
from saturday.canais.whatsapp import webhook as parser
from saturday.canais.whatsapp.cliente import ErroWhatsApp, WhatsAppClient
from saturday.schemas import Attachment, ChatRequest
from saturday.services.transcricao import Transcritor
from saturday.storage.base import Storage

logger = logging.getLogger(__name__)

# O grafo lê foto e PDF; acima disso o modelo de visão não aproveita o arquivo.
LIMITE_LEITURA_BYTES = 4_500_000
MIMES_DE_LEITURA = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})
EXTENSAO_POR_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
}

MAXIMO_TEXTO = 4000


def prefixo_do_canal(numero: str) -> str:
    """`conversation_id` do WhatsApp: estável por telefone."""

    return f"whatsapp:{numero}"


def _mime_limpo(mime: str) -> str:
    """`audio/ogg; codecs=opus` → `audio/ogg`."""

    return mime.split(";", 1)[0].strip().lower()


@dataclass(frozen=True)
class Entrada:
    """O que entrou: ou um turno, ou uma resposta que não precisa do grafo."""

    pedido: ChatRequest | None = None
    resposta_local: str | None = None


class EntradaWhatsApp:
    def __init__(
        self,
        cliente: WhatsAppClient,
        storage: Storage,
        transcritor: Transcritor,
    ) -> None:
        self._cliente = cliente
        self._storage = storage
        self._transcritor = transcritor

    def marcar_lida(self, evento: parser.Evento) -> None:
        """Confirma para o cliente que a mensagem foi recebida.

        Falhar aqui não é motivo para desfazer o turno: o cliente já mandou a
        mensagem, o recibo é cortesia do canal.
        """

        if evento.wamid:
            self._cliente.marcar_lida(evento.phone_number_id, evento.wamid)

    def preparar(self, evento: parser.Evento) -> Entrada:
        conversa = prefixo_do_canal(evento.numero)
        if not evento.roda_turno:
            # Localização, contato, figurinha e reação: só registro.
            return Entrada()

        texto = evento.texto
        anexos: list[Attachment] = []

        if evento.midia is not None:
            try:
                dados, mime_bruto = self._cliente.baixar_midia(evento.midia.id)
            except ErroWhatsApp as exc:
                logger.warning("whatsapp_midia_falhou id=%s erro=%s", evento.midia.id, exc)
                return Entrada(resposta_local=mensagem_midia_ilegivel())

            mime = _mime_limpo(mime_bruto)
            chave = self._arquivar(evento, dados, mime)

            if mime.startswith("audio/"):
                transcricao = self._transcritor.transcrever(dados, mime)
                if not transcricao:
                    return Entrada(resposta_local=mensagem_audio_ilegivel())
                texto = transcricao
            elif mime in MIMES_DE_LEITURA and len(dados) <= LIMITE_LEITURA_BYTES:
                anexos.append(Attachment(chave=chave, mime_type=mime))  # type: ignore[arg-type]

        return Entrada(
            pedido=ChatRequest(
                conversation_id=conversa,
                message_id=evento.evento_id,
                message=texto[:MAXIMO_TEXTO],
                attachments=anexos,
            )
        )

    def _arquivar(self, evento: parser.Evento, dados: bytes, mime: str) -> str:
        extensao = EXTENSAO_POR_MIME.get(mime, "bin")
        chave = f"whatsapp/{evento.numero}/{evento.evento_id}.{extensao}"
        return self._storage.salvar(dados, mime_type=mime, chave=chave)
