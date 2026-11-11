"""Saúde do worker: banco acessível e batimento recente do laço."""

from __future__ import annotations

import os
import time
from pathlib import Path

from saturday.health import LIMITE_BATIMENTO_S, problemas, registrar_batimento


def test_saudavel_com_banco_e_batimento_recente(tmp_path: Path) -> None:
    caminho = tmp_path / "beat"
    registrar_batimento(caminho)

    assert problemas(lambda: True, caminho=caminho) == []


def test_banco_fora_aparece(tmp_path: Path) -> None:
    caminho = tmp_path / "beat"
    registrar_batimento(caminho)

    assert "banco inacessível" in problemas(lambda: False, caminho=caminho)


def test_batimento_ausente_aparece(tmp_path: Path) -> None:
    assert problemas(lambda: True, caminho=tmp_path / "nao-existe") == ["batimento ausente"]


def test_batimento_atrasado_aparece(tmp_path: Path) -> None:
    caminho = tmp_path / "beat"
    caminho.write_text("x", encoding="utf-8")
    atrasado = time.time() - (LIMITE_BATIMENTO_S + 30)
    os.utime(caminho, (atrasado, atrasado))

    achados = problemas(lambda: True, caminho=caminho)

    assert len(achados) == 1
    assert "batimento atrasado" in achados[0]


def test_dois_problemas_ao_mesmo_tempo(tmp_path: Path) -> None:
    assert len(problemas(lambda: False, caminho=tmp_path / "nao-existe")) == 2
