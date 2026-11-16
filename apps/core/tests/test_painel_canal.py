"""O que cada canal permite ao painel (docs/decisoes/0009). Sem banco."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saturday.painel.canal import MODELOS_DO_PAINEL, permitido

AGORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
HA_UMA_HORA = AGORA - timedelta(hours=1)
HA_DOIS_DIAS = AGORA - timedelta(days=2)


@pytest.mark.parametrize(
    ("canal", "entrada", "envia", "janela", "texto_livre", "tem_modelo"),
    [
        ("whatsapp", HA_UMA_HORA, True, "aberta", True, True),
        ("whatsapp", HA_DOIS_DIAS, True, "fechada", False, True),
        # Cliente nunca escreveu: o primeiro contato na Meta é por modelo.
        ("whatsapp", None, True, "fechada", False, True),
        ("evolution", HA_DOIS_DIAS, True, None, True, False),
        ("evolution", None, True, None, True, False),
        ("chat", HA_UMA_HORA, False, None, False, False),
    ],
)
def test_o_que_o_canal_permite(canal, entrada, envia, janela, texto_livre, tem_modelo):
    p = permitido(canal, entrada, AGORA)

    assert (p.envia, p.janela, p.texto_livre) == (envia, janela, texto_livre)
    assert p.modelos == (MODELOS_DO_PAINEL if tem_modelo else ())
