"""Contrato do canal de atendimento.

A origem diz *de onde* veio o turno (e por onde a resposta tem que sair); o
`Envio` é o que vai no outbox para o canal entregar; o `Resultado` é o que o
canal responde ao outbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Canais que entregam por WhatsApp, cada um com o seu provedor (decisão 0009):
# a Cloud API da Meta e a Evolution. Os dois guardam telefone e instância.
CANAIS_WHATSAPP = frozenset({"whatsapp", "evolution"})


class Resultado(StrEnum):
    """O que o canal sabe sobre uma tentativa de entrega.

    O canal classifica e para; quem decide esperar ou desistir é o outbox.
    """

    OK = "ok"
    TEMPORARIO = "temporario"
    # A requisição pode ter sido aceita (timeout de leitura): repetir às cegas
    # duplicaria a mensagem, porque a Meta não tem chave de idempotência.
    TEMPORARIO_INCERTO = "temporario_incerto"
    PERMANENTE = "permanente"
    # A Meta recusou texto porque a janela fechou; o outbox converte para modelo.
    JANELA_FECHADA = "janela_fechada"
    # Janela fechada: o modelo avisou o cliente e o texto espera ele responder.
    AGUARDANDO_CLIENTE = "aguardando_cliente"


@dataclass(frozen=True)
class OrigemCanal:
    """De onde veio a mensagem do cliente."""

    canal: str = "chat"
    telefone: str | None = None
    phone_number_id: str | None = None


@dataclass(frozen=True)
class Envio:
    """O que um canal de WhatsApp precisa para entregar uma linha do outbox.

    É o único lugar que conhece as chaves do `payload`: quem enfileira usa
    `para_payload` e quem entrega, `do_payload`. Mudar uma chave exige migrar
    as linhas que já estão na fila.
    """

    conversation_id: str = ""
    numero: str | None = None
    # Na Evolution, o nome da instância.
    phone_number_id: str | None = None
    texto: str = ""
    # Linha de `mensagens` que recebe o id do provedor e o status de entrega.
    mensagem_id: int | None = None
    # Modelo escolhido por quem envia: sai com a janela aberta ou fechada.
    modelo: str = ""
    # Modelo (e o código do link dele) do aviso quando a janela está fechada.
    modelo_aviso: str = ""
    link_aviso: str = ""
    # Anexo no storage: chave, mime_type, nome e tipo. Nunca o conteúdo.
    midia: dict[str, Any] | None = None
    # Progresso do texto longo; quem grava é o outbox, a cada parte.
    partes_enviadas: int = 0

    def para_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "numero": self.numero,
            "phone_number_id": self.phone_number_id,
            "answer": self.texto,
            "mensagem_id": self.mensagem_id,
        }
        for chave in ("modelo", "modelo_aviso", "link_aviso", "midia"):
            if valor := getattr(self, chave):
                payload[chave] = valor
        return payload

    @classmethod
    def do_payload(cls, payload: dict[str, Any] | None) -> Envio:
        """Lê o que estiver na linha; chave ausente ou de tipo errado vira vazio."""

        dados = payload or {}
        mensagem_id = dados.get("mensagem_id")
        midia = dados.get("midia")
        return cls(
            conversation_id=str(dados.get("conversation_id") or ""),
            numero=str(dados.get("numero") or ""),
            phone_number_id=str(dados.get("phone_number_id") or ""),
            texto=str(dados.get("answer") or ""),
            mensagem_id=mensagem_id if isinstance(mensagem_id, int) else None,
            modelo=str(dados.get("modelo") or ""),
            modelo_aviso=str(dados.get("modelo_aviso") or ""),
            link_aviso=str(dados.get("link_aviso") or ""),
            midia=midia if isinstance(midia, dict) else None,
            partes_enviadas=int(dados.get("partes_enviadas") or 0),
        )
