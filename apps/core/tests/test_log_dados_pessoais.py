"""Regra 9: nenhum dado pessoal inteiro nos logs de uma conversa completa.

A conversa entra pelo webhook da Meta, passa pelo worker e percorre o ramo CLT
até o pagamento (consulta e proposta na Granatech), com tudo o que o processo
registra capturado no formato JSON de produção, campos de `extra` incluídos.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import httpx
import pytest
from conftest import Fakes, _montar_app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_clt_jornada import (  # noqa: F401 - fixtures
    ATE_CONSENTIMENTO,
    CPF,
    TELEFONE,
    FakeBrasilAPI,
    Jornada,
    _montar,
    brasilapi,
    fakes_clt,
)
from test_clt_proposta import DADOS_ATE_RESUMO, DOMINIO, _evento
from test_whatsapp_integracao import NUMERO, PHONE_NUMBER_ID, _entregar_webhook, _webhook_texto

from saturday.canais.whatsapp.cliente import WhatsAppClient
from saturday.canais.whatsapp.entrada import EntradaWhatsApp, prefixo_do_canal
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.jobs.eventos import processar
from saturday.jobs.outbox import EntregadorPorCanal, drenar
from saturday.log import SO_AVISOS, JsonFormatter
from saturday.storage.memoria import MemoriaStorage

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

EMAIL = next(m for m in ATE_CONSENTIMENTO if "@" in m)


def _com_separadores(digitos: str) -> re.Pattern[str]:
    """Os dígitos em sequência, colados ou com pontuação: `001.890.049-67`."""

    return re.compile(r"\D{0,2}".join(digitos))


# Dados fictícios dos fixtures e do simulador da Granatech.
PROIBIDOS = {
    "cpf": _com_separadores(CPF),
    # Sem o 55: pega o número com e sem o código do país.
    "telefone": _com_separadores(TELEFONE),
    "e-mail": re.compile(re.escape(EMAIL), re.IGNORECASE),
    "nome da mãe": re.compile("MAE DE TESTE DA SILVA", re.IGNORECASE),
    "endereço": re.compile("PRACA DA SE", re.IGNORECASE),
}

# Vazamentos que este teste achou e ainda não têm correção decidida (issue #37).
# O `conversation_id` do WhatsApp é `canal:telefone` e vai inteiro no log do
# turno; os outros logs com `conversation_id` (em `agent/service.py`,
# `agent/turno.py` e `services/webhook.py`) têm o mesmo problema.
PENDENTES = {"telefone em saturday.agent.service (turno.py): turno"}


def _vazamentos(registros: list[logging.LogRecord]) -> list[str]:
    """`dado em logger (arquivo): modelo da mensagem`, sem repetir o dado."""

    formatador = JsonFormatter()
    achados = set()
    for registro in registros:
        linha = formatador.format(registro)
        for dado, padrao in PROIBIDOS.items():
            if padrao.search(linha):
                achados.add(f"{dado} em {registro.name} ({registro.filename}): {registro.msg}")
    return sorted(achados)


def _meta_falsa(pedido: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"messages": [{"id": f"wamid.{uuid.uuid4().hex}"}]})


def test_conversa_clt_pelo_webhook_da_meta_nao_deixa_dado_pessoal_no_log(
    fabrica: sessionmaker[Session],
    http_granatech: TestClient,
    fakes_clt: Fakes,  # noqa: F811
    brasilapi: FakeBrasilAPI,  # noqa: F811
    settings: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Como em `configurar_logging` (conferido em `test_log_turno.py`).
    for nome in SO_AVISOS:
        caplog.set_level(logging.WARNING, logger=nome)
    # Por último: cada `set_level` também troca o nível do handler do `caplog`.
    caplog.set_level(logging.DEBUG)
    servico, granatech = _montar(
        fabrica,
        http_granatech,
        fakes_clt,
        brasilapi,
        granatech_proposta_ativa=True,
        dominio_publico=DOMINIO,
        whatsapp_token=settings.whatsapp_token,
        whatsapp_app_secret=settings.whatsapp_app_secret,
        whatsapp_verify_token=settings.whatsapp_verify_token,
        whatsapp_numeros=[PHONE_NUMBER_ID],
    )
    settings = servico.settings
    api = TestClient(_montar_app(settings, servico, fabrica))
    jornada = Jornada(servico, fabrica, granatech)
    jornada.id = prefixo_do_canal(TELEFONE)

    with httpx.Client(transport=httpx.MockTransport(_meta_falsa)) as http:
        meta = WhatsAppClient(http, settings)
        entrada = EntradaWhatsApp(meta, MemoriaStorage(), None)  # type: ignore[arg-type]
        saida = EntregadorPorCanal({"whatsapp": SaidaWhatsApp(meta, fabrica, settings)})

        def entregar() -> None:
            assert drenar(fabrica, saida, settings), "nada saiu pelo outbox"

        def falar(*mensagens: str) -> None:
            for mensagem in mensagens:
                payload = _webhook_texto(mensagem, f"wamid.{uuid.uuid4().hex}")
                _entregar_webhook(api, settings, payload)
                assert processar(fabrica, servico, entrada, settings, granatech) == 1
                entregar()

        assert NUMERO.endswith(TELEFONE)
        falar(*ATE_CONSENTIMENTO, "SIM")
        assert jornada.clt()["etapa"] == "consultando"
        jornada.evento_consulta("SUCCESS")
        entregar()
        falar("1", *DADOS_ATE_RESUMO, "SIM")
        _evento(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO")
        _evento(jornada, "PENDING_PAYMENT", "PAGO")
        entregar()
        assert jornada.clt()["etapa"] == "pago"

    # A rede só vale se os caminhos com dado pessoal de fato registraram algo.
    nomes = {registro.name for registro in caplog.records}
    assert {
        "saturday.agent.service",
        "saturday.bancos.granatech.cliente",
        "saturday.jobs.outbox",
    } <= nomes
    # Igualdade: vazamento novo reprova, e o pendente sai da lista quando for corrigido.
    assert _vazamentos(caplog.records) == sorted(PENDENTES)
