"""Leitura do webhook da Evolution API (v2.3.7, integração Baileys).

Cada POST traz um evento: `messages.upsert` (o que o cliente mandou),
`messages.update` (o que aconteceu com o que nós mandamos) ou
`connection.update` (a instância conectou ou caiu; decisão 0010). Mensagem e
status viram o mesmo
`Evento` do WhatsApp da Meta, com o nome da instância no lugar do
`phone_number_id`, para a entrada e o worker tratarem os dois canais igual.
"""

from __future__ import annotations

import logging
from typing import Any

from saturday.canais.evolution.cliente import telefone_do_jid
from saturday.canais.whatsapp.webhook import Evento, Midia

logger = logging.getLogger(__name__)

# Tipos que viram mídia lida pela entrada (foto, PDF, áudio).
TIPOS_DE_MIDIA = frozenset({"imageMessage", "audioMessage", "documentMessage"})

# Situação da Evolution → a mesma da Meta, que o resto do sistema já entende.
STATUS = {
    "SERVER_ACK": "sent",
    "DELIVERY_ACK": "delivered",
    "READ": "read",
    "PLAYED": "read",
    "ERROR": "failed",
}


def _telefone_do(chave: dict[str, Any]) -> str:
    """Telefone do cliente pela chave da mensagem; vazio se não houver.

    Contato só com `@lid` (sem telefone) e grupo ficam de fora: a conversa é
    identificada pelo celular.
    """

    for campo in ("remoteJid", "remoteJidAlt"):
        telefone = telefone_do_jid(chave.get(campo))
        if telefone:
            return telefone
    return ""


def _de_mensagem(dados: dict[str, Any], instancia: str) -> Evento | None:
    chave = dados.get("key")
    if not isinstance(chave, dict) or chave.get("fromMe"):
        return None
    identificador = chave.get("id")
    if not isinstance(identificador, str) or not identificador:
        return None
    numero = _telefone_do(chave)
    if not numero:
        logger.info("evolution_sem_telefone jid=%s", str(chave.get("remoteJid", ""))[-8:])
        return None

    tipo = str(dados.get("messageType") or "")
    mensagem = dados.get("message")
    mensagem = mensagem if isinstance(mensagem, dict) else {}
    corpo = mensagem.get(tipo)
    corpo = corpo if isinstance(corpo, dict) else {}

    texto = ""
    midia = None
    if tipo == "conversation":
        texto = str(mensagem.get("conversation") or "")
    elif tipo == "extendedTextMessage":
        texto = str(corpo.get("text") or "")
    elif tipo in TIPOS_DE_MIDIA:
        texto = str(corpo.get("caption") or "")
        nome = corpo.get("fileName")
        # A Evolution baixa a mídia pelo id da mensagem.
        midia = Midia(
            id=identificador,
            mime_type=str(corpo.get("mimetype") or ""),
            nome=nome if isinstance(nome, str) else None,
        )

    return Evento(
        tipo="mensagem",
        evento_id=identificador,
        wamid=identificador,
        numero=numero,
        phone_number_id=instancia,
        texto=texto,
        tipo_midia=tipo,
        midia=midia,
        # Vídeo, figurinha, localização, reação e o resto: só registro.
        roda_turno=bool(texto) or midia is not None,
    )


def _de_status(dados: dict[str, Any], instancia: str) -> Evento | None:
    identificador = dados.get("keyId")
    situacao = STATUS.get(str(dados.get("status") or ""))
    if not isinstance(identificador, str) or not identificador or situacao is None:
        return None
    return Evento(
        tipo="status",
        evento_id=f"{identificador}:{situacao}",
        wamid=identificador,
        numero="",
        phone_number_id=instancia,
        status=situacao,
        roda_turno=False,
    )


def eventos(payload: dict[str, Any]) -> list[Evento]:
    """Evento do POST; lista vazia para o que não é mensagem do cliente ou status."""

    instancia = str(payload.get("instance") or "")
    dados = payload.get("data")
    if not instancia or not isinstance(dados, dict):
        return []

    nome = payload.get("event")
    evento = None
    if nome == "messages.upsert":
        evento = _de_mensagem(dados, instancia)
    elif nome == "messages.update":
        evento = _de_status(dados, instancia)
    return [evento] if evento is not None else []


# Estados que a Evolution só manda quando a queda é definitiva (sem nova
# tentativa automática): viram alerta.
ESTADOS_DE_QUEDA = frozenset({"close", "refused"})


def conexao(payload: dict[str, Any]) -> dict[str, Any] | None:
    """`connection.update` achatado; ``None`` se não for um.

    `connecting` não interessa: é o meio do caminho entre o QR e o `open`.
    """

    dados = payload.get("data")
    instancia = str(payload.get("instance") or "")
    if payload.get("event") != "connection.update" or not instancia or not isinstance(dados, dict):
        return None
    estado = str(dados.get("state") or "")
    if estado != "open" and estado not in ESTADOS_DE_QUEDA:
        return None
    return {
        "tipo": "conexao",
        "instancia": instancia,
        "estado": estado,
        "telefone": telefone_do_jid(dados.get("wuid")),
        "motivo": dados.get("statusReason"),
    }
