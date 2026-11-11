"""Os documentos versionados da homologação não carregam segredo nem dado pessoal."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[3] / "docs" / "granatech-homologacao"
CPFS_DE_TESTE = {"00189004967", "00000000000"}
PADROES = {
    "chave hexadecimal": re.compile(r"\b[0-9a-f]{64}\b"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "telefone com DDI": re.compile(r"\+55\s?\d{2}"),
    "e-mail pessoal": re.compile(r"[\w.%+-]+@(gmail|hotmail|outlook|yahoo)\.com", re.I),
}


def _arquivos() -> list[Path]:
    return [p for p in PASTA.rglob("*") if p.is_file() and p.suffix in {".md", ".json"}]


def test_pasta_existe() -> None:
    assert _arquivos()


@pytest.mark.parametrize("arquivo", _arquivos(), ids=lambda p: p.name)
def test_sem_segredos(arquivo: Path) -> None:
    texto = arquivo.read_text(encoding="utf-8")
    for nome, padrao in PADROES.items():
        assert not padrao.search(texto), f"{nome} em {arquivo.name}"
    cpfs = set(re.findall(r"(?<![\d.])\d{11}(?![\d])", texto)) - CPFS_DE_TESTE
    # Telefones de exemplo (11999999999) passam; CPF de verdade não.
    assert cpfs <= {"11999999999"}, f"números de 11 dígitos em {arquivo.name}: {sorted(cpfs)}"
