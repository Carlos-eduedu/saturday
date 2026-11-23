"""Sentry: só erros, sem dado pessoal (decisão 0038)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from saturday import observabilidade
from saturday.observabilidade import iniciar_sentry, limpar_evento
from saturday.privacidade import mascarar_texto
from saturday.settings import Settings

DSN = "https://chave@o0.ingest.sentry.io/1"


def test_mascarar_texto_cobre_cpf_email_e_telefone() -> None:
    texto = (
        "cpf 123.456.789-01, 123456789-02, cpf12345678903, fulana@exemplo.com, "
        "(11) 98765-4321, (11) 987654322, 11 98765 4323, +55 11 98765 4324, "
        "whatsapp:5511987654325 e conta 1234567890123"
    )

    limpo = mascarar_texto(texto)

    for dado in ("123.456.789", "456789", "fulana@", "98765", "8765432", "1234567890"):
        assert dado not in limpo
    assert "***.***.***-01" in limpo
    assert "f***@exemplo.com" in limpo


def test_mascarar_texto_preserva_ids_e_datas() -> None:
    texto = "outbox=42 em 2026-11-23T10:00:00 de 2025-2026 id=123e4567-e89b-12d3"

    assert mascarar_texto(texto) == texto


def test_limpar_evento_mascara_tudo_e_corta_query() -> None:
    evento: Any = {
        "logentry": {
            "message": "consulta_falhou cpf=%s tel=%s rota=%s",
            "params": ("12345678901", 11987654321, "/consultas?nome=Bia"),
        },
        "exception": {"values": [{"type": "ErroGranatech", "value": "e-mail fulana@exemplo.com"}]},
        "breadcrumbs": {
            "values": [
                {
                    "category": "httplib",
                    "data": {"url": "https://api.granatech/consultas?cpf=12345678901&nome=Ana"},
                    "message": "telefone 11987654321",
                }
            ]
        },
    }

    limpo = repr(limpar_evento(evento, {}))

    for dado in ("12345678901", "fulana@", "11987654321", "nome=Ana", "nome=Bia", "?cpf"):
        assert dado not in limpo
    assert "https://api.granatech/consultas" in limpo


def test_sem_dsn_ou_em_pytest_nao_liga() -> None:
    assert not iniciar_sentry(Settings(environment="dev"))
    assert not iniciar_sentry(Settings(environment="pytest", sentry_dsn=DSN))


class _Captura(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture
def captura(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Captura]:
    transporte = _Captura()
    init_real = sentry_sdk.init

    def init_com_captura(*args: Any, **kwargs: Any) -> Any:
        return init_real(*args, transport=transporte, **kwargs)

    monkeypatch.setattr(observabilidade.sentry_sdk, "init", init_com_captura)
    yield transporte
    sentry_sdk.get_client().close()
    # DSN vazio: sem ele o SDK leria `SENTRY_DSN` do ambiente e mandaria de verdade.
    init_real(dsn="", default_integrations=False)
    sentry_sdk.get_isolation_scope().clear()


def test_logger_error_vira_evento_mascarado_e_sem_variaveis(captura: _Captura) -> None:
    assert iniciar_sentry(Settings(environment="dev", sentry_dsn=DSN))

    cpf = "12345678901"
    logging.getLogger("saturday.teste").info("so_breadcrumb_nao cpf=%s", cpf)
    try:
        raise ValueError(f"cpf {cpf}")
    except ValueError:
        logging.getLogger("saturday.teste").exception("granatech_falhou cpf=%s", cpf)
    sentry_sdk.flush()

    eventos = [item.payload.json for env in captura.envelopes for item in env.items]
    eventos = [evento for evento in eventos if evento and evento.get("level") == "error"]
    assert len(eventos) == 1
    texto = repr(eventos[0])
    assert cpf not in texto
    # INFO não vira breadcrumb (o texto aparece nas linhas de código do frame).
    assert "so_breadcrumb_nao" not in repr(eventos[0].get("breadcrumbs"))
    frames = eventos[0]["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in frames)
