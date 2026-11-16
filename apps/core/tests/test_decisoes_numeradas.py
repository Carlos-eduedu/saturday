"""Cada decisão em `docs/decisoes/` tem um número só seu.

Duas sessões em worktrees diferentes pegam o mesmo próximo número sem se ver;
este teste fica vermelho na `main` quando as duas chegam.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

PASTA = Path(__file__).resolve().parents[3] / "docs" / "decisoes"


def test_numero_de_decisao_nao_se_repete() -> None:
    numeros = Counter(p.name[:4] for p in PASTA.glob("[0-9]*.md"))
    assert numeros
    repetidos = sorted(n for n, vezes in numeros.items() if vezes > 1)
    assert not repetidos, f"número de decisão repetido: {repetidos}"
