"""Tradução do evento do WhatsApp em um turno do agente.

Baixa a mídia, guarda no storage e resolve o áudio em texto. O que não dá para
aproveitar vira resposta local, sem rodar o grafo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from saturday.agent.textos import mensagem_audio_ilegivel, mensagem_midia_ilegivel
from saturday.canais.whatsapp import webhook as parser
from saturday.canais.whatsapp.cliente import ErroWhatsApp
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


def prefixo_do_canal(numero: str, canal: str = "whatsapp") -> str:
    """`conversation_id` do canal: estável por telefone.

    O mesmo celular em dois canais são duas conversas (decisão 0009).
    """

    return f"{canal}:{numero}"


class ClienteDeEntrada(Protocol):
    """O que a entrada precisa do provedor: Cloud API da Meta ou Evolution.

    ``instancia`` é o ``phone_number_id`` na Meta e o nome da instância na
    Evolution; os erros seguem a hierarquia de ``ErroWhatsApp``.
    """

    def marcar_lida(self, instancia: str, wamid: str) -> None: ...

    def baixar_midia(self, media_id: str, instancia: str) -> tuple[bytes, str]: ...


def _mime_limpo(mime: str) -> str:
    """`audio/ogg; codecs=opus` → `audio/ogg`."""

    return mime.split(";", 1)[0].strip().lower()


@dataclass(frozen=True)
class Entrada:
    """O que entrou: ou um turno, ou uma resposta que não precisa do grafo."""

    pedido: ChatRequest | None = None
    resposta_local: str | None = None
    # A mensagem do cliente como o painel mostra: com resposta local ela não
    # passa pelo grafo e precisa ser gravada à parte; o áudio vai como anexo.
    conteudo: str = ""
    historico: list[dict[str, str]] = field(default_factory=list)


class EntradaWhatsApp:
    """Evento de WhatsApp (de qualquer canal) em turno."""

    def __init__(
        self,
        cliente: ClienteDeEntrada,
        storage: Storage,
        transcritor: Transcritor,
        *,
        canal: str = "whatsapp",
    ) -> None:
        self.canal = canal
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
        conversa = prefixo_do_canal(evento.numero, self.canal)
        if not evento.roda_turno:
            # Localização, contato, figurinha e reação: só registro.
            return Entrada()

        texto = evento.texto
        anexos: list[Attachment] = []

        if evento.midia is not None:
            try:
                dados, mime_bruto = self._cliente.baixar_midia(
                    evento.midia.id, evento.phone_number_id
                )
            except ErroWhatsApp as exc:
                logger.warning(
                    "midia_falhou canal=%s id=%s erro=%s", self.canal, evento.midia.id, exc
                )
                return Entrada(
                    resposta_local=mensagem_midia_ilegivel(),
                    conteudo=texto or "[mídia que não deu para baixar]",
                )

            mime = _mime_limpo(mime_bruto)
            chave = self._arquivar(evento, dados, mime)

            if mime.startswith("audio/"):
                audio = [{"chave": chave, "mime_type": mime}]
                transcricao = self._transcritor.transcrever(dados, mime)
                if not transcricao:
                    logger.warning(
                        "audio_sem_transcricao canal=%s transcritor_ligado=%s",
                        self.canal,
                        getattr(self._transcritor, "habilitado", True),
                    )
                    return Entrada(
                        resposta_local=mensagem_audio_ilegivel(),
                        conteudo="[áudio]",
                        historico=audio,
                    )
                return Entrada(
                    pedido=ChatRequest(
                        conversation_id=conversa,
                        message_id=evento.evento_id,
                        message=transcricao[:MAXIMO_TEXTO],
                    ),
                    historico=audio,
                )
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
        chave = f"{self.canal}/{evento.numero}/{evento.evento_id}.{extensao}"
        return self._storage.salvar(dados, mime_type=mime, chave=chave)
