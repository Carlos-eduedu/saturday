"""Canal Evolution sem rede nem banco: leitura do webhook e classificação de erro."""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from saturday.canais.evolution import webhook as parser
from saturday.canais.evolution.cliente import EvolutionClient, classificar
from saturday.canais.whatsapp.cliente import ErroIncerto, ErroPermanente, ErroTemporario
from saturday.canais.whatsapp.entrada import prefixo_do_canal
from saturday.settings import Settings

INSTANCIA = "mex-sim"


def _upsert(tipo: str, mensagem: dict[str, Any], **chave: Any) -> dict[str, Any]:
    return {
        "event": "messages.upsert",
        "instance": INSTANCIA,
        "data": {
            "key": {
                "remoteJid": "5511987654321@s.whatsapp.net",
                "fromMe": False,
                "id": "3EB0AAA",
                **chave,
            },
            "message": mensagem,
            "messageType": tipo,
        },
    }


def test_texto_vira_evento_com_telefone_normalizado() -> None:
    [evento] = parser.eventos(_upsert("conversation", {"conversation": "Oi"}))

    assert evento.tipo == "mensagem"
    assert evento.evento_id == "3EB0AAA"
    assert evento.numero == "11987654321"
    assert evento.phone_number_id == INSTANCIA
    assert evento.texto == "Oi"
    assert evento.roda_turno


def test_texto_estendido_tambem_vale() -> None:
    [evento] = parser.eventos(
        _upsert("extendedTextMessage", {"extendedTextMessage": {"text": "a"}})
    )
    assert evento.texto == "a"


@pytest.mark.parametrize(
    ("tipo", "corpo"),
    [
        ("imageMessage", {"mimetype": "image/jpeg", "caption": "extrato"}),
        ("audioMessage", {"mimetype": "audio/ogg; codecs=opus"}),
        ("documentMessage", {"mimetype": "application/pdf", "fileName": "x.pdf"}),
    ],
)
def test_midia_usa_o_id_da_mensagem(tipo: str, corpo: dict[str, Any]) -> None:
    [evento] = parser.eventos(_upsert(tipo, {tipo: corpo}))

    assert evento.midia is not None
    assert evento.midia.id == "3EB0AAA"
    assert evento.midia.mime_type == corpo["mimetype"]
    assert evento.texto == corpo.get("caption", "")
    assert evento.roda_turno


def test_tipo_sem_texto_nem_midia_so_registra() -> None:
    [evento] = parser.eventos(_upsert("stickerMessage", {"stickerMessage": {}}))
    assert not evento.roda_turno


@pytest.mark.parametrize(
    "chave",
    [
        {"fromMe": True},
        {"remoteJid": "120363000000000000@g.us"},
        {"remoteJid": "123456789012345@lid"},
    ],
)
def test_ignora_propria_grupo_e_lid_sem_telefone(chave: dict[str, Any]) -> None:
    assert parser.eventos(_upsert("conversation", {"conversation": "Oi"}, **chave)) == []


def test_lid_com_telefone_alternativo_vale() -> None:
    payload = _upsert(
        "conversation",
        {"conversation": "Oi"},
        remoteJid="123456789012345@lid",
        remoteJidAlt="5511987654321@s.whatsapp.net",
    )
    [evento] = parser.eventos(payload)
    assert evento.numero == "11987654321"


@pytest.mark.parametrize(
    ("situacao", "esperado"),
    [("SERVER_ACK", "sent"), ("DELIVERY_ACK", "delivered"), ("READ", "read"), ("ERROR", "failed")],
)
def test_status_de_entrega(situacao: str, esperado: str) -> None:
    payload = {
        "event": "messages.update",
        "instance": INSTANCIA,
        "data": {"keyId": "3EB0BBB", "fromMe": True, "status": situacao},
    }
    [evento] = parser.eventos(payload)

    assert evento.tipo == "status"
    assert evento.wamid == "3EB0BBB"
    assert evento.evento_id == f"3EB0BBB:{esperado}"
    assert evento.status == esperado


def test_evento_desconhecido_ou_pendente_e_ignorado() -> None:
    assert parser.eventos({"event": "connection.update", "instance": INSTANCIA, "data": {}}) == []
    pendente = {
        "event": "messages.update",
        "instance": INSTANCIA,
        "data": {"keyId": "x", "status": "PENDING"},
    }
    assert parser.eventos(pendente) == []


def test_mesmo_celular_em_dois_canais_sao_duas_conversas() -> None:
    assert prefixo_do_canal("11987654321") == "whatsapp:11987654321"
    assert prefixo_do_canal("11987654321", "evolution") == "evolution:11987654321"


@pytest.mark.parametrize(
    ("status", "corpo", "tipo"),
    [
        (500, {}, ErroTemporario),
        (400, {"response": {"message": ["Error: Connection Closed"]}}, ErroTemporario),
        (400, {"response": {"message": [{"exists": False, "number": "55"}]}}, ErroPermanente),
        (401, {}, ErroPermanente),
        (404, {}, ErroPermanente),
    ],
)
def test_classificacao_de_erro(status: int, corpo: dict[str, Any], tipo: type) -> None:
    assert type(classificar(status, corpo)) is tipo


def _cliente(responder: Any) -> EvolutionClient:
    settings = Settings(
        environment="pytest",
        evolution_url="http://evo",
        evolution_api_key="chave",  # type: ignore[arg-type]
        whatsapp_limite_midia_mb=1,
    )
    return EvolutionClient(httpx.Client(transport=httpx.MockTransport(responder)), settings)


def test_envio_manda_numero_com_ddi_e_devolve_o_id() -> None:
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(201, json={"key": {"id": "3EB0CCC"}})

    assert _cliente(responder).enviar_texto(INSTANCIA, "11987654321", "oi") == "3EB0CCC"
    assert pedidos[0].url.path == f"/message/sendText/{INSTANCIA}"
    assert pedidos[0].headers["apikey"] == "chave"
    assert b'"number":"5511987654321"' in pedidos[0].content.replace(b" ", b"")


def test_timeout_de_leitura_no_envio_e_incerto() -> None:
    def responder(pedido: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=pedido)

    with pytest.raises(ErroIncerto):
        _cliente(responder).enviar_texto(INSTANCIA, "11987654321", "oi")


def test_midia_decodifica_e_respeita_o_limite() -> None:
    def pequena(pedido: httpx.Request) -> httpx.Response:
        dados = base64.b64encode(b"%PDF").decode()
        return httpx.Response(201, json={"base64": dados, "mimetype": "application/pdf"})

    assert _cliente(pequena).baixar_midia("3EB0", INSTANCIA) == (b"%PDF", "application/pdf")

    def grande(pedido: httpx.Request) -> httpx.Response:
        dados = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode()
        return httpx.Response(201, json={"base64": dados, "mimetype": "application/pdf"})

    with pytest.raises(ErroPermanente):
        _cliente(grande).baixar_midia("3EB0", INSTANCIA)
