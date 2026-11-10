"""Testes do fluxo completo de portabilidade."""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import Fakes, resultado_jev

from saturday.portabilidade.mensagem import formatar_valor

TZ = ZoneInfo("America/Sao_Paulo")


def cid() -> str:
    return f"fluxo-{uuid.uuid4()}"


def hoje() -> date:
    return datetime.now(TZ).date()


def idade_anos(anos: int) -> str:
    h = hoje()
    try:
        nascimento = date(h.year - anos, h.month, h.day)
    except ValueError:
        nascimento = date(h.year - anos, 1, 1)
    return nascimento.isoformat()


def inicio_para_pagas(pagas: int) -> str:
    h = hoje()
    ano_ref, mes_ref = (h.year, h.month - 1) if h.month > 1 else (h.year - 1, 12)
    indice_ref = ano_ref * 12 + (mes_ref - 1)
    indice = indice_ref - (pagas - 1)
    return f"{indice % 12 + 1:02d}/{indice // 12}"


def dados_extrato(*, pagas: int = 23) -> dict:
    h = hoje()
    return {
        "ehHiscon": True,
        "especie": "32",
        "liberadoParaEmprestimo": True,
        "dataEmissao": h.strftime("01/%m/%Y"),
        "margemUtilizada": 295.24,
        "margemDisponivel": 100.0,
        "margemReservada": 0.0,
        "margemExtrapolada": 0.0,
        "contratos": [
            {
                "banco": "643 - PINE",
                "situacao": "Ativo",
                "parcela": 295.24,
                "taxaMensal": 1.66,
                "qtdParcelas": 84,
                "inicioDesconto": inicio_para_pagas(pagas),
                "dataInclusao": "01/01/2020",
            }
        ],
    }


def anexo_pdf() -> dict:
    return {
        "base64": base64.b64encode(b"%PDF-1.7 extrato").decode(),
        "mime_type": "application/pdf",
    }


def test_anexo_sem_cliente_pergunta_data_e_depois_calcula(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()
    conversa = cid()

    primeira = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "segue meu extrato",
            "attachments": [anexo_pdf()],
        },
    )
    assert primeira.json()["status"] == "answered"
    assert "data de nascimento" in primeira.json()["answer"].lower()

    segunda = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "12/03/1962",
            "cliente": {"uf": "MS"},
        },
    )
    body = segunda.json()
    assert body["status"] == "answered"
    assert body["answer"].startswith("Analisei o seu extrato.")
    assert body["portability_result"]["ok"] is True
    assert any(c["elegivel"] for c in body["portability_result"]["contratos"])
    assert fakes.jev.chamadas == []


def test_cliente_completo_calcula_direto(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()

    r = client.post(
        "/chat",
        json={
            "conversation_id": cid(),
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    )
    body = r.json()
    assert body["status"] == "answered"
    assert body["portability_result"]["ok"] is True
    assert "Quer seguir com a portabilidade?" in body["answer"]


def test_idade_65_sem_uf_pergunta_uf_e_alerta_webplus(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()
    conversa = cid()

    primeira = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(65)},
        },
    )
    assert primeira.json()["status"] == "answered"
    assert "UF" in primeira.json()["answer"]

    segunda = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "PB"},
    )
    body = segunda.json()
    assert body["status"] == "answered"
    assert body["portability_result"]["alerta_webplus"] is True
    assert "mora em PB" in body["answer"]
    assert "assinar o contrato em papel" in body["answer"]


@pytest.mark.parametrize(
    "idade,motivo",
    [(72, "idade_prazo_96"), (74, "idade_fora_regra")],
)
def test_idades_limite_vao_para_handoff(client, fakes: Fakes, idade, motivo):
    fakes.llm.extrato = dados_extrato()

    r = client.post(
        "/chat",
        json={
            "conversation_id": cid(),
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(idade), "uf": "MS"},
        },
    )
    body = r.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == motivo
    assert body["portability_result"]["motivo"] == motivo


def test_valores_da_mensagem_vem_do_result(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()

    body = client.post(
        "/chat",
        json={
            "conversation_id": cid(),
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    ).json()

    resultado = body["portability_result"]
    faixa = resultado["troco_faixa"]
    assert f"R$ {formatar_valor(faixa['min'])}" in body["answer"]
    assert f"R$ {formatar_valor(faixa['max'])}" in body["answer"]
    elegivel = next(c for c in resultado["contratos"] if c["elegivel"])
    assert elegivel["banco"] in body["answer"]
    assert f"R$ {formatar_valor(elegivel['troco_faixa']['min'])}" in body["answer"]
    assert f"R$ {formatar_valor(elegivel['troco_faixa']['max'])}" in body["answer"]


def test_oferta_pendente_aceita_vai_para_handoff(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()
    conversa = cid()

    oferta = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    )
    assert oferta.json()["status"] == "answered"

    fakes.jev.resultado = resultado_jev(
        resposta_oferta="aceita",
        resposta_conf=0.9,
    )
    aceite = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "pode seguir"},
    )
    body = aceite.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "aceitou_portabilidade"


def test_recusa_da_oferta_encerra_sem_handoff(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()
    conversa = cid()

    client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    )

    fakes.jev.resultado = resultado_jev(
        resposta_oferta="recusa",
        resposta_conf=0.9,
    )
    body = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "não quero"},
    ).json()
    assert body["status"] == "answered"
    assert body["handoff_reason"] is None


def test_data_invalida_duas_vezes_vai_para_handoff(client, fakes: Fakes):
    fakes.llm.extrato = dados_extrato()
    conversa = cid()

    client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
        },
    )
    primeira = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "data inválida"},
    )
    assert primeira.json()["status"] == "answered"

    segunda = client.post(
        "/chat",
        json={"conversation_id": conversa, "message": "de novo inválida"},
    )
    body = segunda.json()
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == "dados_cliente_nao_informados"


def test_webhook_contem_portability_result(client, fakes: Fakes):
    fakes.webhook.configurado = True
    fakes.llm.extrato = dados_extrato()

    conversa = cid()
    r = client.post(
        "/chat",
        json={
            "conversation_id": conversa,
            "message": "",
            "attachments": [anexo_pdf()],
            "cliente": {"data_nascimento": idade_anos(64), "uf": "MS"},
        },
    )

    assert r.status_code == 202
    assert len(fakes.webhook.enviados) == 1
    payload = fakes.webhook.enviados[0]
    assert payload["portability_result"]["ok"] is True
    assert payload["portability_result"]["contratos"]
