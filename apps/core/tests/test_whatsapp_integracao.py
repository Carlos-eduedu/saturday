"""Ponta a ponta do canal WhatsApp, com o simulador da Meta em HTTP real.

O caminho exercitado é o de produção: webhook assinado → fila de eventos →
turno no worker → outbox → cliente Graph → simulador.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from conftest import Fakes
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.canais.whatsapp.cliente import WhatsAppClient
from saturday.canais.whatsapp.entrada import EntradaWhatsApp
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.dados.modelos import Conversa, Mensagem
from saturday.jobs.eventos import processar
from saturday.jobs.outbox import EntregadorPorCanal, drenar
from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage

CAMINHO_SIMULADOR = Path(__file__).resolve().parents[3] / "simuladores" / "meta" / "app.py"
PHONE_NUMBER_ID = "100000000000001"
NUMERO = "5511987654321"
NUMERO_NORMALIZADO = "11987654321"


class TranscritorFalso:
    """Devolve sempre o mesmo texto: o provedor real é externo ao repositório."""

    def __init__(self, texto: str = "quero fazer portabilidade") -> None:
        self.texto = texto
        self.chamadas: list[str] = []

    def transcrever(self, dados: bytes, mime_type: str) -> str | None:
        self.chamadas.append(mime_type)
        return self.texto


def _porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("simulador_meta_e2e", CAMINHO_SIMULADOR)
    assert spec is not None
    assert spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def simulador() -> Iterator[str]:
    """Sobe o simulador num porto livre e devolve a base URL."""

    porta = _porta_livre()
    base = f"http://127.0.0.1:{porta}"
    os.environ["SIMULADOR_BASE_URL"] = base

    modulo = _carregar()
    server = uvicorn.Server(
        uvicorn.Config(modulo.app, host="127.0.0.1", port=porta, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    assert server.started

    yield base

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def limpar_estado(simulador: str, checkpointer_pg: Any) -> None:
    """Cada teste começa do zero.

    O simulador vive o módulo inteiro; os checkpoints do LangGraph vivem até
    entre execuções. Sem apagar o thread, o mesmo `wamid` de uma rodada anterior
    faria o turno novo ser tratado como duplicado.
    """

    checkpointer_pg.delete_thread(f"whatsapp:{NUMERO_NORMALIZADO}")
    with httpx.Client(timeout=5.0) as http:
        http.post(f"{simulador}/admin/limpar")


@pytest.fixture
def canais(
    simulador: str,
    settings: Settings,
    fabrica: sessionmaker[Session],
    storage: MemoriaStorage,
) -> Iterator[tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso]]:
    configurado = settings.model_copy(update={"whatsapp_graph_url": simulador})
    http = httpx.Client(timeout=httpx.Timeout(10.0))
    try:
        cliente = WhatsAppClient(http, configurado)
        transcritor = TranscritorFalso()
        entrada = EntradaWhatsApp(cliente, storage, transcritor)  # type: ignore[arg-type]
        saida = SaidaWhatsApp(cliente, fabrica, configurado)
        yield http, entrada, saida, transcritor
    finally:
        http.close()


def _webhook_texto(texto: str, wamid: str) -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": NUMERO,
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _webhook_midia(tipo: str, media_id: str, mime: str, wamid: str) -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": NUMERO,
                                    "timestamp": "1",
                                    "type": tipo,
                                    tipo: {"id": media_id, "mime_type": mime},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _entregar_webhook(
    client: TestClient,
    settings: Settings,
    payload: dict[str, Any],
) -> None:
    corpo = json.dumps(payload).encode()
    segredo = settings.whatsapp_app_secret.get_secret_value()
    assinatura = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    resposta = client.post(
        "/webhooks/whatsapp",
        content=corpo,
        headers={"content-type": "application/json", "x-hub-signature-256": assinatura},
    )
    assert resposta.status_code == 200


def _criar_midia(http: httpx.Client, base: str, dados: bytes, mime: str) -> str:
    resposta = http.post(f"{base}/admin/midia", params={"mime": mime}, content=dados)
    assert resposta.status_code == 200
    return str(resposta.json()["id"])


def _enviadas(http: httpx.Client, base: str) -> list[dict[str, Any]]:
    resposta = http.get(f"{base}/admin/enviadas")
    assert resposta.status_code == 200
    return list(resposta.json()["enviadas"])


def _processar_e_entregar(
    fabrica: sessionmaker[Session],
    service: AgentService,
    entrada: EntradaWhatsApp,
    saida: SaidaWhatsApp,
    settings: Settings,
) -> None:
    processar(fabrica, service, entrada, settings)
    drenar(
        fabrica,
        EntregadorPorCanal({"whatsapp": saida}),
        settings,
    )


def test_texto_chega_ao_grafo_e_volta_pelo_outbox(
    client_pg: TestClient,
    settings: Settings,
    fakes: Fakes,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, _transcritor = canais
    _entregar_webhook(client_pg, settings, _webhook_texto("Quero portabilidade", "wamid.T1"))

    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    enviadas = _enviadas(http, simulador)
    assert enviadas, "nada saiu para o simulador"
    assert enviadas[-1]["type"] == "text"
    assert enviadas[-1]["to"] == NUMERO_NORMALIZADO
    assert enviadas[-1]["text"]["body"]
    assert fakes.jev.chamadas, "o grafo não rodou"


def test_foto_do_extrato_chega_como_anexo_arquivado(
    client_pg: TestClient,
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
    storage: MemoriaStorage,
) -> None:
    http, entrada, saida, _transcritor = canais
    media_id = _criar_midia(http, simulador, b"%PDF-1.4 extrato", "application/pdf")
    _entregar_webhook(
        client_pg,
        settings,
        _webhook_midia("document", media_id, "application/pdf", "wamid.F1"),
    )

    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    # O arquivo foi para o storage, na chave determinística do wamid.
    chave = f"whatsapp/{NUMERO_NORMALIZADO}/wamid.F1.pdf"
    assert storage.existe(chave)
    assert _enviadas(http, simulador)


def test_audio_e_transcrito_e_vira_turno(
    client_pg: TestClient,
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, transcritor = canais
    media_id = _criar_midia(http, simulador, b"OggS audio", "audio/ogg")
    _entregar_webhook(
        client_pg, settings, _webhook_midia("audio", media_id, "audio/ogg", "wamid.A1")
    )

    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    assert transcritor.chamadas == ["audio/ogg"]
    assert _enviadas(http, simulador)


def test_audio_sem_transcricao_pede_texto(
    client_pg: TestClient,
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, transcritor = canais
    transcritor.texto = ""
    media_id = _criar_midia(http, simulador, b"OggS", "audio/ogg")
    _entregar_webhook(
        client_pg, settings, _webhook_midia("audio", media_id, "audio/ogg", "wamid.A2")
    )

    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    enviadas = _enviadas(http, simulador)
    assert enviadas
    assert "texto" in enviadas[-1]["text"]["body"].lower()


def test_janela_fechada_sai_como_modelo(
    client_pg: TestClient,
    settings: Settings,
    fabrica: sessionmaker[Session],
    service_pg: AgentService,
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, _transcritor = canais
    _entregar_webhook(client_pg, settings, _webhook_texto("oi", "wamid.M1"))
    processar(fabrica, service_pg, entrada, settings)

    # Simula a janela fechada: sem mensagem recente do cliente.
    with fabrica() as sessao:
        conversa = sessao.scalar(
            select(Conversa).where(Conversa.conversation_id == f"whatsapp:{NUMERO_NORMALIZADO}")
        )
        assert conversa is not None
        conversa.ultima_entrada_em = None
        sessao.commit()

    drenar(fabrica, EntregadorPorCanal({"whatsapp": saida}), settings)

    enviadas = _enviadas(http, simulador)
    assert enviadas
    assert enviadas[-1]["type"] == "template"
    assert enviadas[-1]["template"]["name"] == "atualizacao_pedido"
    assert enviadas[-1]["template"]["language"]["code"] == "pt_BR"


def test_status_de_entrega_atualiza_a_mensagem(
    client_pg: TestClient,
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, _transcritor = canais
    _entregar_webhook(client_pg, settings, _webhook_texto("oi", "wamid.S1"))
    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    wamid = _enviadas(http, simulador)[-1]["wamid"]
    status = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "statuses": [{"id": wamid, "status": "read", "recipient_id": NUMERO}],
                        }
                    }
                ]
            }
        ]
    }
    _entregar_webhook(client_pg, settings, status)
    processar(fabrica, service_pg, entrada, settings)

    with fabrica() as sessao:
        linha = sessao.scalar(select(Mensagem).where(Mensagem.wamid == wamid))
    assert linha is not None
    assert linha.status_entrega == "read"


def test_webhook_duplicado_nao_gera_dois_turnos(
    client_pg: TestClient,
    settings: Settings,
    fakes: Fakes,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canais: tuple[httpx.Client, EntradaWhatsApp, SaidaWhatsApp, TranscritorFalso],
    simulador: str,
) -> None:
    http, entrada, saida, _transcritor = canais
    payload = _webhook_texto("oi", "wamid.D1")
    _entregar_webhook(client_pg, settings, payload)
    _entregar_webhook(client_pg, settings, payload)

    _processar_e_entregar(fabrica, service_pg, entrada, saida, settings)

    assert len(fakes.jev.chamadas) == 1
    assert len(_enviadas(http, simulador)) == 1
