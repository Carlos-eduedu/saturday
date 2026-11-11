"""Leitura do payload do webhook da Meta.

O webhook chega em `entry[].changes[].value` com duas listas independentes:
`messages` (o que o cliente mandou) e `statuses` (o que aconteceu com o que nós
mandamos). Tudo é traduzido para um `Evento` achatado antes de tocar no banco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from saturday.canais.whatsapp.telefone import normalizar_telefone

# Tipos só registrados: não viram turno, mas o painel precisa saber que chegaram.
TIPOS_SEM_TURNO = frozenset({"location", "contacts", "sticker", "reaction", "video"})


@dataclass(frozen=True)
class Midia:
    id: str
    mime_type: str
    nome: str | None = None


@dataclass(frozen=True)
class Evento:
    tipo: Literal["mensagem", "status"]
    evento_id: str
    numero: str
    phone_number_id: str
    # `wamid` puro: o status usa ele para achar a mensagem; o `evento_id` do
    # status leva a situação junto, porque o mesmo wamid recebe várias.
    wamid: str = ""
    texto: str = ""
    tipo_midia: str = ""
    midia: Midia | None = None
    status: str | None = None
    referral: dict[str, Any] | None = field(default=None)
    roda_turno: bool = True


def _texto_de(mensagem: dict[str, Any]) -> tuple[str, bool]:
    """Texto da mensagem e se ela veio de botão/interativo."""

    tipo = mensagem.get("type")
    if tipo == "text":
        corpo = mensagem.get("text")
        if isinstance(corpo, dict):
            return str(corpo.get("body") or ""), False
    if tipo == "button":
        corpo = mensagem.get("button")
        if isinstance(corpo, dict):
            return str(corpo.get("text") or ""), True
    if tipo == "interactive":
        corpo = mensagem.get("interactive")
        if isinstance(corpo, dict):
            for chave in ("button_reply", "list_reply"):
                resposta = corpo.get(chave)
                if isinstance(resposta, dict):
                    return str(resposta.get("title") or ""), True
    return "", False


def _midia_de(mensagem: dict[str, Any]) -> Midia | None:
    tipo = str(mensagem.get("type") or "")
    corpo = mensagem.get(tipo)
    if not isinstance(corpo, dict):
        return None
    identificador = corpo.get("id")
    if not isinstance(identificador, str):
        return None
    nome = corpo.get("filename")
    return Midia(
        id=identificador,
        mime_type=str(corpo.get("mime_type") or ""),
        nome=str(nome) if isinstance(nome, str) else None,
    )


def _de_mensagem(mensagem: dict[str, Any], phone_number_id: str) -> Evento | None:
    wamid = mensagem.get("id")
    numero = mensagem.get("from")
    if not isinstance(wamid, str) or not isinstance(numero, str):
        return None

    tipo = str(mensagem.get("type") or "")
    texto, interativo = _texto_de(mensagem)
    midia = _midia_de(mensagem)
    referral = mensagem.get("referral")

    return Evento(
        tipo="mensagem",
        evento_id=wamid,
        wamid=wamid,
        numero=normalizar_telefone(numero),
        phone_number_id=phone_number_id,
        texto=texto,
        tipo_midia=tipo,
        midia=midia,
        referral=referral if isinstance(referral, dict) else None,
        # Botão e interativo valem como resposta digitada: viram turno.
        roda_turno=bool(texto) or interativo or midia is not None or tipo not in TIPOS_SEM_TURNO,
    )


def _de_status(status: dict[str, Any], phone_number_id: str) -> Evento | None:
    wamid = status.get("id")
    destinatario = status.get("recipient_id")
    situacao = status.get("status")
    if not isinstance(wamid, str) or not isinstance(situacao, str):
        return None

    return Evento(
        tipo="status",
        # O mesmo wamid recebe sent, delivered, read: cada um é um evento.
        evento_id=f"{wamid}:{situacao}",
        wamid=wamid,
        numero=normalizar_telefone(str(destinatario or "")),
        phone_number_id=phone_number_id,
        status=situacao,
        roda_turno=False,
    )


def eventos(payload: dict[str, Any]) -> list[Evento]:
    """Achata o payload em eventos. Ignora o que não é de mensagem ou status."""

    encontrados: list[Evento] = []
    for entrada in payload.get("entry") or []:
        if not isinstance(entrada, dict):
            continue
        for mudanca in entrada.get("changes") or []:
            if not isinstance(mudanca, dict):
                continue
            valor = mudanca.get("value")
            if not isinstance(valor, dict):
                continue
            metadados = valor.get("metadata")
            phone_number_id = ""
            if isinstance(metadados, dict):
                phone_number_id = str(metadados.get("phone_number_id") or "")

            for mensagem in valor.get("messages") or []:
                if isinstance(mensagem, dict):
                    evento = _de_mensagem(mensagem, phone_number_id)
                    if evento is not None:
                        encontrados.append(evento)

            for status in valor.get("statuses") or []:
                if isinstance(status, dict):
                    evento_status = _de_status(status, phone_number_id)
                    if evento_status is not None:
                        encontrados.append(evento_status)

    return encontrados
