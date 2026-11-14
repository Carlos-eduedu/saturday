"""Mensagens fixas do ramo CLT, lidas de ``conhecimento/clt/mensagens.yaml``.

O arquivo fica na raiz do monorepo (e em ``/app`` na imagem). Ele é procurado a
partir do diretório atual subindo até a raiz, porque a API e o worker rodam da
raiz e os testes rodam de ``apps/core``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Any

import yaml

RELATIVO = Path("conhecimento") / "clt" / "mensagens.yaml"


def localizar(inicio: Path | None = None) -> Path:
    base = (inicio or Path.cwd()).resolve()
    for pasta in (base, *base.parents):
        caminho = pasta / RELATIVO
        if caminho.is_file():
            return caminho
    raise FileNotFoundError(f"{RELATIVO} não encontrado a partir de {base}")


@lru_cache
def _carregar() -> tuple[str, dict[str, str]]:
    dados: Any = yaml.safe_load(localizar().read_text(encoding="utf-8"))
    mensagens = {str(k): str(v).strip() for k, v in dados["mensagens"].items()}
    return str(dados["versao"]), mensagens


def versao() -> str:
    return _carregar()[0]


def chaves() -> dict[str, str]:
    return dict(_carregar()[1])


def variaveis(modelo: str) -> set[str]:
    return {campo for _, campo, _, _ in Formatter().parse(modelo) if campo}


class Fixo(str):
    """Texto de mensagem fixa que lembra a própria chave (procedência no painel).

    Só vive dentro do turno: o estado e o banco recebem ``str`` puro, para que
    o checkpoint nunca precise serializar a subclasse.
    """

    chave: str

    def __new__(cls, valor: str, chave: str) -> Fixo:
        fixo = super().__new__(cls, valor)
        fixo.chave = chave
        return fixo


def texto(chave: str, **valores: object) -> Fixo:
    """Texto da chave com as variáveis preenchidas; faltando uma, levanta erro."""

    modelo = _carregar()[1][chave]
    faltando = variaveis(modelo) - valores.keys()
    if faltando:
        raise KeyError(f"mensagem {chave!r} sem as variáveis {sorted(faltando)}")
    return Fixo(modelo.format(**valores), chave)


def chave_de(*partes: str) -> str | None:
    """Chaves das partes fixas, na ordem do texto, juntas com ``+``."""

    return "+".join(p.chave for p in partes if p and isinstance(p, Fixo)) or None
