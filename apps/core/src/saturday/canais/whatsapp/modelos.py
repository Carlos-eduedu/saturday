"""Modelos aprovados na Meta (`pt_BR`).

Fora da janela de 24 h só modelo pode ser enviado. As definições aqui são as do
piloto: nome, categoria e se levam botão de URL. Os textos dos modelos são
cadastrados na Meta, não neste repositório — o que sai daqui é só a referência e
os parâmetros.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Categoria = Literal["utilidade", "marketing"]


@dataclass(frozen=True)
class Modelo:
    nome: str
    categoria: Categoria
    # Botão de URL aponta para `https://{DOMINIO}/l/{codigo}`: só o código vai
    # como parâmetro, o domínio fica no cadastro do modelo.
    tem_link: bool = False


MODELOS: dict[str, Modelo] = {
    modelo.nome: modelo
    for modelo in (
        Modelo("atualizacao_pedido", "utilidade"),
        Modelo("autorizacao_pendente", "utilidade"),
        Modelo("assinatura_pronta", "utilidade", tem_link=True),
        Modelo("assinatura_refazer", "utilidade", tem_link=True),
        Modelo("dados_bancarios_pendentes", "utilidade"),
        Modelo("pagamento_confirmado", "utilidade"),
        # Marketing exige opt-in, e "Não quero receber" grava opt-out.
        Modelo("recontato_tempo_casa", "marketing"),
    )
}

IDIOMA = "pt_BR"


def componentes(
    parametros: list[str],
    *,
    sufixo_link: str | None = None,
) -> list[dict[str, Any]]:
    """Corpo com variáveis posicionais e, se houver, o parâmetro do botão."""

    partes: list[dict[str, Any]] = []
    if parametros:
        partes.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": parametro} for parametro in parametros],
            }
        )
    if sufixo_link:
        partes.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": sufixo_link}],
            }
        )
    return partes
