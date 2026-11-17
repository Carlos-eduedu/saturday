"""Regra 9: o `conversation_id` do WhatsApp leva o telefone e vai mascarado para o log.

Onde a conversa já existe no banco, o log leva também o `conversa_ref`, o id
da linha em `conversas`. Exige Postgres.
"""

from __future__ import annotations

import logging
import uuid

import httpx
import pytest
from conftest import _url_sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import Conversa, UsuarioPainel
from saturday.dados.sessao import criar_engine
from saturday.dados.sessao import sessao as abrir
from saturday.log import JsonFormatter
from saturday.painel import sessoes
from saturday.privacidade import mascarar_conversation_id
from saturday.schemas import ChatRequest
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings

TELEFONE = "11987654321"
CONVERSA = f"whatsapp:{TELEFONE}"
MASCARADA = "whatsapp:(11) *****-4321"
ORIGEM = OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001")


@pytest.mark.parametrize(
    ("conversation_id", "no_log"),
    [
        (CONVERSA, MASCARADA),
        ("evolution:2133334444", "evolution:(21) *****-4444"),
        ("whatsapp:123", "whatsapp:***"),
        # O `POST /chat` aceita qualquer id: só muda o que tem cara de telefone.
        ("log-turno", "log-turno"),
        ("crm:42", "crm:42"),
        ("teste-0123456789ab", "teste-0123456789ab"),
        ("5511987654321", "(55) *****-4321"),
        ("cliente-11987654321@crm", "cliente-(11) *****-4321@crm"),
    ],
)
def test_mascara_do_conversation_id(conversation_id: str, no_log: str) -> None:
    assert mascarar_conversation_id(conversation_id) == no_log


def _linhas(caplog: pytest.LogCaptureFixture, mensagem: str) -> list[str]:
    """As linhas JSON de produção dos registros cuja mensagem começa por `mensagem`."""

    formatador = JsonFormatter()
    linhas = {formatador.format(r): r for r in caplog.records if r.name.startswith("saturday")}
    assert not [linha for linha in linhas if TELEFONE in linha]
    return [linha for linha, r in linhas.items() if r.getMessage().split(" ")[0] == mensagem]


def _ref(fabrica) -> str:
    with abrir(fabrica) as s:
        return str(s.scalar(select(Conversa.id).where(Conversa.conversation_id == CONVERSA)))


def test_log_do_turno_leva_o_codigo_da_conversa_e_o_telefone_mascarado(service, fabrica, caplog):
    caplog.set_level(logging.INFO)

    service.process_message(ChatRequest(conversation_id=CONVERSA, message="oi"), ORIGEM)

    [registro] = [r for r in caplog.records if r.getMessage() == "turno"]
    assert registro.conversation_id == MASCARADA
    assert registro.conversa_ref == _ref(fabrica)
    assert _linhas(caplog, "turno")


def test_erro_interno_nao_registra_o_telefone(service, fabrica, caplog, monkeypatch):
    def quebra(*_args, **_kwargs):
        raise RuntimeError("grafo caiu")

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(service.graph, "stream", quebra)
    monkeypatch.setattr(service.graph, "update_state", quebra)

    resposta = service.process_message(ChatRequest(conversation_id=CONVERSA, message="oi"), ORIGEM)

    assert resposta.status == "handoff"
    ref = _ref(fabrica)
    for mensagem in ("erro_interno", "falha_ao_gravar_erro_interno"):
        [linha] = _linhas(caplog, mensagem)
        assert f"{mensagem} conversa_ref={ref} conversation_id={MASCARADA}" in linha
    [turno] = [r for r in caplog.records if r.getMessage() == "turno"]
    assert (turno.conversa_ref, turno.conversation_id) == (ref, MASCARADA)


def test_reiniciar_nao_registra_o_telefone(service, fabrica, caplog):
    with abrir(fabrica) as s:
        membro = sessoes.criar_usuario(s, "dev@exemplo.test", "senha-bem-comprida-1", "atendente")
        s.execute(
            update(UsuarioPainel)
            .where(UsuarioPainel.id == membro.id)
            .values(telefone=TELEFONE, pode_testar_fluxos=True)
        )
    service.process_message(ChatRequest(conversation_id=CONVERSA, message="oi"), ORIGEM)
    caplog.set_level(logging.INFO)

    service.process_message(ChatRequest(conversation_id=CONVERSA, message="/reiniciar"), ORIGEM)

    [linha] = _linhas(caplog, "conversa_reiniciada")
    assert f"conversa_reiniciada conversa_ref={_ref(fabrica)} conversation_id={MASCARADA}" in linha


def test_turno_de_sistema_sem_conversa_nao_registra_o_telefone(service, caplog):
    assert service.continuar(CONVERSA, "consulta_pronta") is None

    [linha] = _linhas(caplog, "turno_de_sistema_sem_conversa")
    assert f"conversation_id={MASCARADA} evento=consulta_pronta" in linha


def test_desistencia_sem_conversa_nao_registra_o_telefone(service, caplog):
    service.desistir_de_sistema(CONVERSA, "consulta_pronta")

    [linha] = _linhas(caplog, "desistencia_sem_conversa")
    assert f"conversation_id={MASCARADA} evento=consulta_pronta" in linha


def test_processamento_em_segundo_plano_que_falha_nao_registra_o_telefone(
    service, caplog, monkeypatch
):
    def quebra(*_args, **_kwargs):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(service, "process_message", quebra)

    service.processar_e_enviar(ChatRequest(conversation_id=CONVERSA, message="oi"))

    [linha] = _linhas(caplog, "processamento_falhou")
    assert f"conversation_id={MASCARADA} erro=RuntimeError" in linha


def test_webhook_que_falha_nao_registra_o_telefone(caplog):
    def fora_do_ar(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fora do ar", request=request)

    settings = Settings(
        environment="pytest",
        webhook_url="https://webhook.test/agent",
        webhook_secret="segredo",  # noqa: S106 - segredo de teste
    )
    with httpx.Client(transport=httpx.MockTransport(fora_do_ar)) as http:
        payload = {"conversation_id": CONVERSA, "status": "answered", "id": uuid.uuid4().hex}
        assert WebhookClient(http, settings).enviar(payload) is False

    [linha] = _linhas(caplog, "webhook_falhou")
    assert f"conversation_id={MASCARADA} status=answered erro=ConnectError" in linha


def test_erro_nao_tratado_nao_registra_o_telefone_do_caminho(app, service, caplog, monkeypatch):
    def quebra(*_args, **_kwargs):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(service, "liberar", quebra)

    resposta = TestClient(app, raise_server_exceptions=False).post(
        f"/conversations/{CONVERSA}/release"
    )

    assert resposta.status_code == 500
    [linha] = _linhas(caplog, "erro_nao_tratado")
    assert f"rota=/conversations/{MASCARADA}/release erro=RuntimeError" in linha


def test_erro_do_banco_nao_leva_os_parametros_da_consulta(settings, pg_url):
    # O `logger.exception` grava a mensagem do erro, e a do SQLAlchemy trazia os
    # parâmetros da consulta: `conversation_id`, telefone, CPF.
    engine = criar_engine(settings, url=_url_sqlalchemy(pg_url))
    try:
        with pytest.raises(DBAPIError) as erro, engine.connect() as conexao:
            conexao.execute(text("SELECT :id FROM tabela_que_nao_existe"), {"id": CONVERSA})
    finally:
        engine.dispose()

    assert "tabela_que_nao_existe" in str(erro.value)
    assert TELEFONE not in str(erro.value)
