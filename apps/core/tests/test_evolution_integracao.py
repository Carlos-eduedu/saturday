"""Ponta a ponta do canal Evolution, com o simulador em HTTP real.

Webhook com token → fila de eventos → turno no worker → outbox → cliente da
Evolution → simulador. Também cobre o status de entrega, a saída sem janela e o
envio do painel.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from conftest import Fakes
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.clt.mensagens import texto as mensagem
from saturday.agent.service import AgentService
from saturday.canais.base import Resultado
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.canais.evolution.saida import SaidaEvolution
from saturday.canais.whatsapp.entrada import EntradaWhatsApp
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, EventoRecebido, Mensagem, Outbox, UsuarioPainel
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs.eventos import processar
from saturday.jobs.outbox import EntregadorPorCanal, drenar
from saturday.painel import acoes
from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage

CAMINHO_SIMULADOR = Path(__file__).resolve().parents[3] / "simuladores" / "evolution" / "app.py"
INSTANCIA = "mex-sim"
NUMERO = "5511987654321"
NUMERO_NORMALIZADO = "11987654321"
CONVERSA = f"evolution:{NUMERO_NORMALIZADO}"
TOKEN = "token-do-simulador"  # noqa: S105 - valor do simulador


class TranscritorFalso:
    def transcrever(self, dados: bytes, mime_type: str) -> str | None:
        return "quero fazer portabilidade"


def _porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("simulador_evolution_e2e", CAMINHO_SIMULADOR)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def simulador() -> Iterator[tuple[str, ModuleType]]:
    porta = _porta_livre()
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
    yield f"http://127.0.0.1:{porta}", modulo
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def settings(settings: Settings, simulador: tuple[str, ModuleType]) -> Settings:
    base, _ = simulador
    return settings.model_copy(
        update={
            "evolution_ativo": True,
            "evolution_url": base,
            "evolution_api_key": SecretStr("chave-do-simulador"),
            "evolution_webhook_token": SecretStr(TOKEN),
        }
    )


@pytest.fixture(autouse=True)
def limpar_estado(simulador: tuple[str, ModuleType], checkpointer_pg: Any) -> None:
    checkpointer_pg.delete_thread(CONVERSA)
    _, modulo = simulador
    modulo.limpar()


@pytest.fixture
def canal(
    settings: Settings,
    fabrica: sessionmaker[Session],
    storage: MemoriaStorage,
) -> Iterator[tuple[EntradaWhatsApp, SaidaEvolution]]:
    with httpx.Client(timeout=httpx.Timeout(10.0)) as http:
        cliente = EvolutionClient(http, settings)
        entrada = EntradaWhatsApp(cliente, storage, TranscritorFalso(), canal="evolution")  # type: ignore[arg-type]
        yield entrada, SaidaEvolution(cliente, fabrica)


def _upsert(identificador: str, tipo: str, mensagem_: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "messages.upsert",
        "instance": INSTANCIA,
        "data": {
            "key": {"remoteJid": f"{NUMERO}@s.whatsapp.net", "fromMe": False, "id": identificador},
            "message": mensagem_,
            "messageType": tipo,
        },
    }


def _webhook(client: TestClient, payload: dict[str, Any], token: str = TOKEN) -> int:
    resposta = client.post("/webhooks/evolution", json=payload, headers={"x-webhook-token": token})
    return resposta.status_code


def _rodar(
    fabrica: sessionmaker[Session],
    service: AgentService,
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    settings: Settings,
) -> None:
    entrada, saida = canal
    processar(fabrica, service, None, settings, evolution=entrada)  # type: ignore[arg-type]
    drenar(fabrica, EntregadorPorCanal({"evolution": saida}), settings)


def test_texto_chega_ao_grafo_e_volta_pela_evolution(
    client_pg: TestClient,
    settings: Settings,
    fakes: Fakes,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
) -> None:
    assert _webhook(client_pg, _upsert("3EB0T1", "conversation", {"conversation": "Oi"})) == 200

    _rodar(fabrica, service_pg, canal, settings)

    _, modulo = simulador
    assert fakes.jev.chamadas, "o grafo não rodou"
    assert modulo.ENVIADAS, "nada saiu para o simulador"
    assert modulo.ENVIADAS[-1]["instancia"] == INSTANCIA
    assert modulo.ENVIADAS[-1]["number"] == NUMERO
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == CONVERSA)
        ).one()
        assert conversa.canal == "evolution"
        assert conversa.phone_number_id == INSTANCIA


def test_foto_vai_para_o_storage_e_vira_anexo(
    client_pg: TestClient,
    settings: Settings,
    fakes: Fakes,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
    storage: MemoriaStorage,
) -> None:
    _, modulo = simulador
    modulo.MIDIAS["3EB0F1"] = (b"%PDF-1.4 extrato", "application/pdf")
    payload = _upsert(
        "3EB0F1", "documentMessage", {"documentMessage": {"mimetype": "application/pdf"}}
    )
    assert _webhook(client_pg, payload) == 200

    _rodar(fabrica, service_pg, canal, settings)

    assert storage.existe(f"evolution/{NUMERO_NORMALIZADO}/3EB0F1.pdf")


def test_status_de_entrega_atualiza_a_mensagem(
    client_pg: TestClient,
    settings: Settings,
    service_pg: AgentService,
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
) -> None:
    _webhook(client_pg, _upsert("3EB0S1", "conversation", {"conversation": "Oi"}))
    _rodar(fabrica, service_pg, canal, settings)
    _, modulo = simulador
    enviado = modulo.ENVIADAS[0]["id"]

    status = {
        "event": "messages.update",
        "instance": INSTANCIA,
        "data": {"keyId": enviado, "fromMe": True, "status": "DELIVERY_ACK"},
    }
    assert _webhook(client_pg, status) == 200
    _rodar(fabrica, service_pg, canal, settings)

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(select(Mensagem).where(Mensagem.wamid == enviado)).one()
        assert linha.status_entrega == "delivered"


def test_webhook_recusa_token_errado_e_deduplica(
    client_pg: TestClient,
    fabrica: sessionmaker[Session],
) -> None:
    payload = _upsert("3EB0D1", "conversation", {"conversation": "Oi"})
    assert _webhook(client_pg, payload, token="errado") == 401  # noqa: S106

    assert _webhook(client_pg, payload) == 200
    assert _webhook(client_pg, payload) == 200

    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.scalars(
            select(EventoRecebido).where(EventoRecebido.origem == "evolution")
        ).all()
        assert [linha.evento_id for linha in linhas] == ["3EB0D1"]


def _conversa_evolution(fabrica: sessionmaker[Session], *, dias_sem_escrever: int) -> int:
    with abrir_sessao(fabrica) as sessao:
        conversa = repositorios.obter_ou_criar_conversa(
            sessao,
            CONVERSA,
            canal="evolution",
            telefone=NUMERO_NORMALIZADO,
            phone_number_id=INSTANCIA,
        )
        conversa.ultima_entrada_em = datetime.now(UTC) - timedelta(days=dias_sem_escrever)
        sessao.flush()
        return conversa.id


def _linha(fabrica: sessionmaker[Session], conversa_id: int, **payload: Any) -> Outbox:
    with abrir_sessao(fabrica) as sessao:
        enfileirar(
            sessao,
            conversa_id=conversa_id,
            canal="evolution",
            payload={"numero": NUMERO_NORMALIZADO, "phone_number_id": INSTANCIA, **payload},
        )
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(select(Outbox).where(Outbox.conversa_id == conversa_id)).one()
        sessao.expunge(linha)
        return linha


def test_sem_janela_o_aviso_proativo_sai_como_texto(
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
) -> None:
    conversa_id = _conversa_evolution(fabrica, dias_sem_escrever=3)
    linha = _linha(fabrica, conversa_id, answer="Pagamento confirmado!", modelo_aviso="x")

    assert canal[1].entregar(linha) is Resultado.OK
    _, modulo = simulador
    assert modulo.ENVIADAS[-1]["text"] == "Pagamento confirmado!"


def test_modelo_de_recontato_sai_como_texto(
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
) -> None:
    conversa_id = _conversa_evolution(fabrica, dias_sem_escrever=60)
    linha = _linha(fabrica, conversa_id, answer="", modelo="recontato_tempo_casa")

    assert canal[1].entregar(linha) is Resultado.OK
    _, modulo = simulador
    assert modulo.ENVIADAS[-1]["text"] == mensagem("recontato_tempo_casa_texto")


@pytest.mark.parametrize(
    ("falha", "esperado"),
    [({"status": 500}, Resultado.TEMPORARIO), ({"inexistente": True}, Resultado.PERMANENTE)],
)
def test_falha_da_evolution_e_classificada(
    fabrica: sessionmaker[Session],
    canal: tuple[EntradaWhatsApp, SaidaEvolution],
    simulador: tuple[str, ModuleType],
    falha: dict[str, Any],
    esperado: Resultado,
) -> None:
    _, modulo = simulador
    modulo.FALHAS.append(falha)
    conversa_id = _conversa_evolution(fabrica, dias_sem_escrever=0)
    linha = _linha(fabrica, conversa_id, answer="oi")

    assert canal[1].entregar(linha) is esperado


def test_painel_envia_texto_sem_janela_e_recusa_modelo(fabrica: sessionmaker[Session]) -> None:
    conversa_id = _conversa_evolution(fabrica, dias_sem_escrever=5)
    with abrir_sessao(fabrica) as sessao:
        usuario = UsuarioPainel(email="evolution@exemplo.com", senha_hash="x", perfil="atendente")
        sessao.add(usuario)
        sessao.flush()
        conversa = sessao.get(Conversa, conversa_id)
        assert conversa is not None
        conversa.atendimento = "assumida"
        conversa.atendente_id = usuario.id
        sessao.flush()

        acoes.enviar(sessao, conversa, usuario.id, texto="Oi", modelo=None)
        with pytest.raises(acoes.AcaoRecusada):
            acoes.enviar(sessao, conversa, usuario.id, texto=None, modelo="atualizacao_pedido")
        linha = sessao.scalars(select(Outbox).where(Outbox.conversa_id == conversa_id)).one()
        assert linha.canal == "evolution"
