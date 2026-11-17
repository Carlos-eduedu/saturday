"""Log por turno, sem conteúdo de mensagem."""

from __future__ import annotations

import logging
import subprocess
import sys


def test_log_do_turno_tem_caminho_e_custo_sem_texto(client, fakes, caplog):
    caplog.set_level(logging.INFO, logger="saturday.agent.service")
    texto = "texto secreto do cliente"

    resposta = client.post(
        "/chat",
        json={"conversation_id": "log-turno", "message": texto},
    )
    assert resposta.status_code == 200

    registros = [r for r in caplog.records if r.getMessage() == "turno"]
    assert len(registros) == 1
    registro = registros[0]
    assert registro.status == "answered"
    assert "classify_intent" in registro.caminho
    assert "generate_answer" in registro.caminho
    assert hasattr(registro, "custo_total_usd")
    assert texto not in caplog.text


def test_access_log_nao_grava_query_string():
    from saturday.log import SemQueryString

    registro = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/admin/conversas?busca=987654321", "1.1", 200),
        None,
    )
    SemQueryString().filter(registro)
    assert "987654321" not in registro.getMessage()
    assert "/admin/conversas" in registro.getMessage()


def test_log_do_httpx_com_a_url_da_chamada_fica_calado():
    # Em outro processo: `configurar_logging` troca os handlers do logger raiz.
    codigo = (
        "import logging; from saturday.log import LOGGERS_SO_AVISOS, configurar_logging; "
        "configurar_logging('DEBUG'); "
        "print([logging.getLogger(n).isEnabledFor(logging.INFO) for n in LOGGERS_SO_AVISOS])"
    )
    saida = subprocess.run(  # noqa: S603 - argumentos fixos
        [sys.executable, "-c", codigo], capture_output=True, text=True, check=True
    )
    assert saida.stdout.strip() == "[False, False]"
