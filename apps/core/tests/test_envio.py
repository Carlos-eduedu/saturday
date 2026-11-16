"""`Envio` (canais/base.py): as chaves do payload do outbox em um lugar só."""

from __future__ import annotations

from saturday.canais.base import Envio


def test_payload_minimo_tem_as_cinco_chaves_de_sempre() -> None:
    envio = Envio(
        conversation_id="c1",
        numero="5511999990000",
        phone_number_id="100",
        texto="oi",
        mensagem_id=7,
    )

    assert envio.para_payload() == {
        "conversation_id": "c1",
        "numero": "5511999990000",
        "phone_number_id": "100",
        "answer": "oi",
        "mensagem_id": 7,
    }


def test_opcionais_so_entram_quando_preenchidos() -> None:
    midia = {
        "chave": "anexos/a.pdf",
        "mime_type": "application/pdf",
        "nome": "a.pdf",
        "tipo": "document",
    }
    envio = Envio(
        conversation_id="c1",
        numero="5511999990000",
        phone_number_id="100",
        mensagem_id=7,
        modelo="retomada",
        modelo_aviso="link_assinatura",
        link_aviso="abc123",
        midia=midia,
    )

    payload = envio.para_payload()

    assert payload["modelo"] == "retomada"
    assert payload["modelo_aviso"] == "link_assinatura"
    assert payload["link_aviso"] == "abc123"
    assert payload["midia"] == midia
    # O progresso das partes é do outbox: quem enfileira não o grava.
    assert "partes_enviadas" not in payload


def test_ida_e_volta_pelo_payload() -> None:
    envio = Envio(
        conversation_id="c1",
        numero="5511999990000",
        phone_number_id="100",
        texto="oi",
        mensagem_id=7,
        modelo="retomada",
        link_aviso="abc123",
    )

    assert Envio.do_payload(envio.para_payload()) == envio


def test_leitura_tolera_linha_antiga_ou_estragada() -> None:
    assert Envio.do_payload(None) == Envio(numero="", phone_number_id="")

    lido = Envio.do_payload(
        {
            "numero": None,
            "answer": None,
            "mensagem_id": "7",
            "midia": "anexo",
            "partes_enviadas": 2,
            "status": "answered",
        }
    )

    assert lido.numero == ""
    assert lido.texto == ""
    # Id que não é inteiro não marca mensagem nenhuma.
    assert lido.mensagem_id is None
    assert lido.midia is None
    assert lido.partes_enviadas == 2
