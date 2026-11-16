"""O que o painel pode fazer pelo canal de uma conversa, agora.

Janela de 24 h e modelo só existem na Cloud API da Meta; a Evolution manda
texto e anexo a qualquer hora; o canal `chat` não envia pelo painel
(docs/decisoes/0009). Quem precisa dessa regra pergunta aqui, e a API entrega a
resposta pronta ao painel: nenhum outro lugar compara o canal para decidir
envio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from saturday.canais.base import CANAIS_WHATSAPP
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS

# Modelos que o atendente pode mandar: utilidade e sem botão de link.
# TODO: variáveis de modelo quando os textos forem cadastrados na Meta; os
# links `/l/{codigo}` só existem na Fase 6.
MODELOS_DO_PAINEL = tuple(
    nome
    for nome, modelo in MODELOS.items()
    if modelo.categoria == "utilidade" and not modelo.tem_link
)

CANAL_COM_JANELA = "whatsapp"


@dataclass(frozen=True)
class Permitido:
    # O painel manda mensagem por este canal.
    envia: bool
    # `None` no canal que não tem janela.
    janela: Literal["aberta", "fechada"] | None
    modelos: tuple[str, ...]

    @property
    def texto_livre(self) -> bool:
        """Texto e anexo, agora. Com a janela fechada, só modelo."""

        return self.envia and self.janela != "fechada"


def permitido(canal: str, ultima_entrada_em: datetime | None, agora: datetime) -> Permitido:
    if canal != CANAL_COM_JANELA:
        return Permitido(envia=canal in CANAIS_WHATSAPP, janela=None, modelos=())
    aberta = janela_aberta(ultima_entrada_em, agora)
    return Permitido(
        envia=True,
        janela="aberta" if aberta else "fechada",
        modelos=MODELOS_DO_PAINEL,
    )
