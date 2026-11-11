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


def texto(chave: str, **valores: object) -> str:
    """Texto da chave com as variáveis preenchidas; faltando uma, levanta erro."""

    modelo = _carregar()[1][chave]
    faltando = variaveis(modelo) - valores.keys()
    if faltando:
        raise KeyError(f"mensagem {chave!r} sem as variáveis {sorted(faltando)}")
    return modelo.format(**valores)
