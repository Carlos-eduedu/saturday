"""Regras do canal WhatsApp: telefone, partes, janela, modelos, assinatura e parser."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from saturday.canais.whatsapp.cliente import (
    CODIGOS_TEMPORARIOS,
    ErroJanelaFechada,
    ErroPermanente,
    ErroTemporario,
    classificar,
)
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS, componentes
from saturday.canais.whatsapp.partes import MAX_CARACTERES, MAX_PARTES, dividir
from saturday.canais.whatsapp.telefone import normalizar_telefone
from saturday.canais.whatsapp.webhook import eventos
from saturday.web.api.whatsapp import assinatura_valida

AGORA = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("5511987654321", "11987654321"),  # 13 dígitos com o 55
        ("551187654321", "11987654321"),  # 12 dígitos, ganha o nono
        ("11987654321", "11987654321"),  # já normalizado
        ("1132654321", "1132654321"),  # fixo: sem nono dígito
        ("+55 (11) 98765-4321", "11987654321"),  # pontuação é ignorada
    ],
)
def test_normalizar_telefone(bruto: str, esperado: str) -> None:
    assert normalizar_telefone(bruto) == esperado


def test_dividir_por_linha_em_branco() -> None:
    assert dividir("primeiro\n\nsegundo") == ["primeiro", "segundo"]


def test_dividir_respeita_o_teto_de_partes_sem_perder_texto() -> None:
    texto = "\n\n".join(f"parte {numero}" for numero in range(1, 9))
    partes = dividir(texto)

    assert len(partes) == MAX_PARTES
    # O que passou do teto entra na última parte, não é descartado.
    assert "parte 8" in partes[-1]


def test_dividir_fatia_texto_longo() -> None:
    partes = dividir("x" * (MAX_CARACTERES * 2 + 10))

    assert len(partes) == 3
    assert all(len(parte) <= MAX_CARACTERES for parte in partes)


def test_dividir_texto_vazio() -> None:
    assert dividir("   \n\n  ") == []


def test_janela_aberta_dentro_de_24h() -> None:
    assert janela_aberta(AGORA - timedelta(hours=23), AGORA) is True


def test_janela_fechada_depois_de_24h() -> None:
    assert janela_aberta(AGORA - timedelta(hours=25), AGORA) is False


def test_janela_fechada_sem_mensagem_do_cliente() -> None:
    assert janela_aberta(None, AGORA) is False


def test_as_sete_mensagens_do_piloto_estao_definidas() -> None:
    assert set(MODELOS) == {
        "atualizacao_pedido",
        "autorizacao_pendente",
        "assinatura_pronta",
        "assinatura_refazer",
        "dados_bancarios_pendentes",
        "pagamento_confirmado",
        "recontato_tempo_casa",
    }
    assert MODELOS["recontato_tempo_casa"].categoria == "marketing"


def test_componentes_com_corpo_e_botao() -> None:
    partes = componentes(["João"], sufixo_link="abc123")

    assert partes[0]["type"] == "body"
    assert partes[0]["parameters"] == [{"type": "text", "text": "João"}]
    assert partes[1]["sub_type"] == "url"
    assert partes[1]["parameters"] == [{"type": "text", "text": "abc123"}]


def test_assinatura_confere() -> None:
    corpo = b'{"a":1}'
    digest = hmac.new(b"segredo", corpo, hashlib.sha256).hexdigest()

    assert assinatura_valida(corpo, f"sha256={digest}", "segredo") is True


@pytest.mark.parametrize(
    "cabecalho",
    [None, "", "sha256=errado", "sha1=abc"],
)
def test_assinatura_recusa_cabecalho_ruim(cabecalho: str | None) -> None:
    assert assinatura_valida(b"{}", cabecalho, "segredo") is False


def test_assinatura_recusa_corpo_alterado() -> None:
    digest = hmac.new(b"segredo", b'{"a":1}', hashlib.sha256).hexdigest()

    assert assinatura_valida(b'{"a":2}', f"sha256={digest}", "segredo") is False


def test_classificar_erro_temporario_por_status() -> None:
    assert isinstance(classificar(503, {}), ErroTemporario)


def test_classificar_codigos_temporarios() -> None:
    for codigo in CODIGOS_TEMPORARIOS:
        assert isinstance(classificar(400, {"error": {"code": codigo}}), ErroTemporario)


def test_classificar_erro_permanente() -> None:
    assert isinstance(classificar(400, {"error": {"code": 131026}}), ErroPermanente)


def test_classificar_janela_fechada_nao_e_permanente() -> None:
    assert isinstance(classificar(400, {"error": {"code": 131047}}), ErroJanelaFechada)


def test_parser_de_texto() -> None:
    encontrados = eventos(_payload_mensagem({"type": "text", "text": {"body": "oi"}}))

    assert len(encontrados) == 1
    evento = encontrados[0]
    assert evento.tipo == "mensagem"
    assert evento.texto == "oi"
    assert evento.numero == "11987654321"
    assert evento.phone_number_id == "100000000000001"
    assert evento.roda_turno is True


def test_parser_de_botao_vira_turno() -> None:
    evento = eventos(_payload_mensagem({"type": "button", "button": {"text": "Sim"}}))[0]

    assert evento.texto == "Sim"
    assert evento.roda_turno is True


def test_parser_de_interativo_usa_o_titulo() -> None:
    payload = _payload_mensagem(
        {"type": "interactive", "interactive": {"button_reply": {"title": "Autorizo"}}}
    )

    assert eventos(payload)[0].texto == "Autorizo"


def test_parser_de_imagem_traz_midia() -> None:
    evento = eventos(
        _payload_mensagem({"type": "image", "image": {"id": "m1", "mime_type": "image/jpeg"}})
    )[0]

    assert evento.midia is not None
    assert evento.midia.id == "m1"
    assert evento.roda_turno is True


def test_parser_de_audio_traz_midia_e_tipo() -> None:
    evento = eventos(
        _payload_mensagem({"type": "audio", "audio": {"id": "a1", "mime_type": "audio/ogg"}})
    )[0]

    assert evento.tipo_midia == "audio"
    assert evento.midia is not None


@pytest.mark.parametrize(
    ("tipo", "corpo"),
    [
        ("location", {"latitude": -23.5, "longitude": -46.6}),
        ("contacts", {}),
        ("reaction", {"message_id": "wamid.X", "emoji": "👍"}),
        # Figurinha e vídeo trazem `id` de mídia, como no payload real da Meta.
        ("sticker", {"id": "s1", "mime_type": "image/webp", "animated": False}),
        ("video", {"id": "v1", "mime_type": "video/mp4"}),
    ],
)
def test_tipos_so_registrados_nao_rodam_turno(tipo: str, corpo: dict[str, object]) -> None:
    evento = eventos(_payload_mensagem({"type": tipo, tipo: corpo}))[0]

    assert evento.roda_turno is False


def test_parser_de_status_gera_evento_por_situacao() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "p1"},
                            "statuses": [
                                {"id": "wamid.X", "status": "delivered", "recipient_id": "5511..."}
                            ],
                        }
                    }
                ]
            }
        ]
    }

    evento = eventos(payload)[0]
    assert evento.tipo == "status"
    assert evento.wamid == "wamid.X"
    assert evento.evento_id == "wamid.X:delivered"
    assert evento.roda_turno is False


def test_parser_guarda_referral_de_anuncio() -> None:
    payload = _payload_mensagem(
        {
            "type": "text",
            "text": {"body": "oi"},
            "referral": {"source_url": "https://fb.me/x", "headline": "Anúncio"},
        }
    )

    assert eventos(payload)[0].referral is not None


def _payload_mensagem(mensagem: dict[str, object]) -> dict[str, object]:
    completa = {
        "id": "wamid.W",
        "from": "5511987654321",
        "timestamp": "1",
        **mensagem,
    }
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "100000000000001"},
                            "messages": [completa],
                        }
                    }
                ]
            }
        ]
    }
