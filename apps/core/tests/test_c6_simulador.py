"""Rota de saúde e rotas de administração do simulador do C6, em processo."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

ACCEPT = "application/vnd.c6bank_error_data_v2+json"
SIMULACAO = {
    "operation_type": "NOVA",
    "product_type_code": "0001",
    "simulation_type": "POR_VALOR_SOLICITADO",
    "formalization_subtype": "DIGITAL_WEB",
    "promoter_code": "000000",
    "covenant_group": "INSS",
    "public_agency": "000001",
    "installment_quantity": 84,
    "requested_amount": 1000,
    "client": {
        "tax_identifier": "00000000000",
        "enrollment": "0000000000",
        "birth_date": "1960-01-01",
        "income_amount": 2000,
    },
}
PROPOSTA = {
    "origin": {"x": 1},
    "credit_condition": {"x": 1},
    "payment": {"x": 1},
    "client": SIMULACAO["client"],
}


def _login(http: TestClient) -> dict[str, Any]:
    resposta = http.post(
        "/auth/token",
        data={"username": "usuario-do-simulador", "password": "senha-do-simulador"},
    )
    corpo: dict[str, Any] = resposta.json()
    return corpo


def _token(http: TestClient) -> str:
    return str(_login(http)["access_token"])


def _simular(http: TestClient, token: str) -> tuple[int, dict[str, Any]]:
    resposta = http.post(
        "/marketplace/proposal/simulation",
        json=SIMULACAO,
        headers={"Authorization": token, "Accept": ACCEPT},
    )
    return resposta.status_code, resposta.json()


def test_saude_responde_sem_token(http_c6: TestClient) -> None:
    resposta = http_c6.get("/saude")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_config_troca_o_cenario_da_simulacao(http_c6: TestClient) -> None:
    token = _token(http_c6)

    resposta = http_c6.post("/admin/config", json={"formato": "lista", "expira_s": 60})

    assert resposta.status_code == 200
    assert resposta.json()["formato"] == "lista"
    status, corpo = _simular(http_c6, token)
    assert status == 200
    assert [c["monthly_customer_rate"] for c in corpo["credit_conditions"]] == [1.75, 1.8, 1.85]
    assert _login(http_c6)["expires_in_seconds"] == 60


def test_config_recusa_chave_desconhecida(http_c6: TestClient) -> None:
    resposta = http_c6.post("/admin/config", json={"taxa": 2.0})

    assert resposta.status_code == 400
    assert "taxa" in resposta.json()["message"]
    assert "taxa" not in http_c6.get("/admin/estado").json()["config"]


def test_falha_programada_vale_uma_vez(http_c6: TestClient) -> None:
    token = _token(http_c6)

    resposta = http_c6.post(
        "/admin/falha", json={"rota": "/marketplace/proposal/simulation", "status": 500}
    )

    assert resposta.json() == {"programadas": 1}
    assert _simular(http_c6, token)[0] == 500
    assert _simular(http_c6, token)[0] == 200


def test_falha_com_registrar_inclui_a_proposta_antes_de_falhar(http_c6: TestClient) -> None:
    cabecalhos = {"Authorization": _token(http_c6), "Accept": ACCEPT}
    http_c6.post(
        "/admin/falha", json={"rota": "/marketplace/proposal", "metodo": "POST", "registrar": True}
    )

    resposta = http_c6.post("/marketplace/proposal", json=PROPOSTA, headers=cabecalhos)

    assert resposta.status_code == 500
    assert list(http_c6.get("/admin/estado").json()["propostas"]) == ["960000001"]


def test_falha_sem_rota_e_recusada(http_c6: TestClient) -> None:
    resposta = http_c6.post("/admin/falha", json={"status": 500})

    assert resposta.status_code == 400
    assert http_c6.get("/admin/estado").json()["falhas"] == []


def test_falhas_programadas_podem_ser_limpas(http_c6: TestClient) -> None:
    token = _token(http_c6)
    http_c6.post("/admin/falha", json={"rota": "/marketplace/proposal/simulation"})

    resposta = http_c6.delete("/admin/falha")

    assert resposta.json() == {"programadas": 0}
    assert _simular(http_c6, token)[0] == 200


def test_estado_mostra_config_falhas_propostas_e_chamadas(http_c6: TestClient) -> None:
    cabecalhos = {"Authorization": _token(http_c6), "Accept": ACCEPT}
    http_c6.post("/marketplace/proposal", json=PROPOSTA, headers=cabecalhos)
    falha = {"rota": "/marketplace/proposal", "metodo": "GET", "status": 401}
    http_c6.post("/admin/falha", json=falha)

    estado = http_c6.get("/admin/estado").json()

    assert estado["config"]["formato"] == "unico"
    assert estado["falhas"] == [falha]
    assert estado["propostas"]["960000001"]["origin"] == {"x": 1}
    assert estado["logins"] == 1
    assert estado["chamadas"] == [["POST", "/auth/token"], ["POST", "/marketplace/proposal"]]


def test_limpar_reinicia_tudo_e_volta_a_config_padrao(http_c6: TestClient) -> None:
    token = _token(http_c6)
    cabecalhos = {"Authorization": token, "Accept": ACCEPT}
    http_c6.post("/marketplace/proposal", json=PROPOSTA, headers=cabecalhos)
    http_c6.post("/admin/config", json={"formato": "lista"})
    http_c6.post("/admin/falha", json={"rota": "/marketplace/proposal"})

    resposta = http_c6.post("/admin/limpar")

    assert resposta.json() == {"ok": 1}
    estado = http_c6.get("/admin/estado").json()
    assert estado["config"]["formato"] == "unico"
    assert (estado["falhas"], estado["propostas"], estado["logins"]) == ([], {}, 0)
    # O token de antes deixou de valer.
    assert _simular(http_c6, token)[0] == 401
