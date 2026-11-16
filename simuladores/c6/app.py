"""Simulador da API do C6 Consignado (contrato novo e refinanciamento INSS).

Emula só o que o Saturday usa, com as rotas, os cabeçalhos e os campos do
"Manual API V31.5" do banco: login, simulação, inclusão, consulta e link de
formalização. Tudo em memória. `FALHAS` programa erros (401, 500), com a opção
de executar a operação antes de falhar: o caso "incerto" de uma proposta.

O manual não mostra o corpo das respostas de erro nem as situações da esteira:
o que está aqui é uma forma plausível, marcada com TODO(c6).

Rodar local:
    uvicorn app:app --app-dir simuladores/c6 --port 8300
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Simulador do C6 Consignado", version="0.1.0")

USUARIO = os.environ.get("SIMULADOR_C6_USUARIO", "usuario-do-simulador")
SENHA = os.environ.get("SIMULADOR_C6_SENHA", "senha-do-simulador")

ACCEPT_ERRO = "application/vnd.c6bank_error_data_v2+json"
ACCEPT_CONSULTA = "application/vnd.c6bank_fgts_consult_v2+json"
ACCEPT_LINK = "application/vnd.c6bank_url_consult_v1+json"

# Parâmetros mutáveis pelos testes.
CONFIG: dict[str, Any] = {
    "expira_s": 1199,  # o exemplo do manual
    "taxa_mensal": 1.8,
    # "unico": uma condição, como no manual. "lista": `credit_conditions`.
    "formato": "unico",
    "saldo_refin": 1500.0,  # saldo devedor de cada contrato refinanciado
}

TAXAS_DA_LISTA = [1.75, 1.8, 1.85]

TOKENS: dict[str, float] = {}
PROPOSTAS: dict[str, dict[str, Any]] = {}
FALHAS: list[dict[str, Any]] = []
LOGINS: list[float] = []
CHAMADAS: list[tuple[str, str]] = []


def limpar() -> None:
    TOKENS.clear()
    PROPOSTAS.clear()
    FALHAS.clear()
    LOGINS.clear()
    CHAMADAS.clear()


def _erro(status: int, mensagem: str) -> JSONResponse:
    # TODO(c6): qual é o corpo de erro (application/vnd.c6bank_error_data_v2+json)?
    return JSONResponse(status_code=status, content={"message": mensagem})


def _falha_programada(request: Request) -> tuple[Response | None, bool]:
    """Consome a primeira falha da rota; devolve o erro e se a operação roda antes."""

    for falha in FALHAS:
        if falha.get("metodo", request.method) != request.method:
            continue
        if request.url.path != falha.get("rota"):
            continue
        FALHAS.remove(falha)
        return _erro(int(falha.get("status", 500)), "falha simulada"), bool(falha.get("registrar"))
    return None, False


def _barrar(request: Request, accept: str) -> Response | None:
    """Token no `Authorization`, sem "Bearer", e o `Accept` da rota."""

    CHAMADAS.append((request.method, request.url.path))
    expira = TOKENS.get(request.headers.get("authorization", ""))
    if expira is None or expira <= time.time():
        return _erro(401, "token inválido")
    if request.headers.get("accept") != accept:
        return _erro(406, "Accept não aceito")
    return None


@app.post("/auth/token")
async def login(request: Request) -> Response:
    CHAMADAS.append(("POST", "/auth/token"))
    campos = parse_qs((await request.body()).decode())
    if campos.get("username") != [USUARIO] or campos.get("password") != [SENHA]:
        return _erro(401, "usuário ou senha inválidos")
    token = uuid.uuid4().hex
    TOKENS[token] = time.time() + float(CONFIG["expira_s"])
    LOGINS.append(time.time())
    return JSONResponse({"access_token": token, "expires_in_seconds": CONFIG["expira_s"]})


def _price(taxa: float, parcelas: int) -> float:
    """Fator que leva o valor financiado à parcela (tabela Price)."""

    return taxa / (1 - (1 + taxa) ** -parcelas)


@app.post("/marketplace/proposal/simulation")
async def simular(request: Request) -> Response:
    barrado = _barrar(request, ACCEPT_ERRO)
    if barrado:
        return barrado
    erro, _ = _falha_programada(request)
    if erro:
        return erro
    corpo = await request.json()
    cliente = corpo.get("client") or {}
    obrigatorios = (
        "operation_type",
        "product_type_code",
        "simulation_type",
        "formalization_subtype",
        "promoter_code",
        "covenant_group",
        "public_agency",
        "installment_quantity",
    )
    do_cliente = ("tax_identifier", "enrollment", "birth_date", "income_amount")
    refin = corpo.get("operation_type") == "REFINANCIAMENTO"
    por_parcela = corpo.get("simulation_type") == "POR_VALOR_PARCELA"
    pedido = "installment_amount" if por_parcela else "requested_amount"
    faltando = [c for c in (*obrigatorios, pedido) if corpo.get(c) in (None, "")]
    faltando += [f"client.{c}" for c in do_cliente if cliente.get(c) in (None, "")]
    contratos = corpo.get("refinancing_contracts") or []
    if refin and not contratos:
        faltando.append("refinancing_contracts")
    if faltando:
        return _erro(400, "campos obrigatórios: " + ", ".join(faltando))

    taxas = TAXAS_DA_LISTA if CONFIG["formato"] == "lista" else [float(CONFIG["taxa_mensal"])]
    saldo = float(CONFIG["saldo_refin"]) * len(contratos) if refin else 0.0
    condicoes = [_condicao(corpo, taxa, refin, saldo, contratos) for taxa in taxas]
    if CONFIG["formato"] == "lista":
        # TODO(c6): a lista de condições não está no manual; é o que a operação
        # da MEX recebe hoje (12 convênios em 3 faixas de taxa).
        return JSONResponse({"credit_conditions": condicoes})
    return JSONResponse(condicoes[0])


def _condicao(
    corpo: dict[str, Any], taxa_mensal: float, refin: bool, saldo: float, contratos: list[str]
) -> dict[str, Any]:
    parcelas = int(corpo["installment_quantity"])
    taxa = taxa_mensal / 100
    fator = _price(taxa, parcelas)
    if corpo.get("simulation_type") == "POR_VALOR_PARCELA":
        parcela = float(corpo["installment_amount"])
        principal = round(parcela / fator, 2)
    else:
        principal = round(float(corpo["requested_amount"]), 2)
        parcela = round(principal * fator, 2)
    iof = round(principal * 0.03, 2)
    liquido = round(principal - iof, 2)
    return {
        "covenant": {
            "code": ("0010" if refin else "2101") + f"{round(taxa_mensal * 100) % 100:02d}",
            "description": "INSS Refin - Web" if refin else "INSS ML Normal - Web",
        },
        "product": {
            "code": "000035" if refin else "000030",
            "description": "INSS REFIN DWEB" if refin else "INSS ML DWEB",
        },
        "installment_quantity": parcelas,
        "requested_amount": liquido,
        "principal_amount": principal,
        "installment_amount": parcela,
        "gross_amount": round(parcela * parcelas, 2),
        "iof_amount": iof,
        "net_amount": liquido,
        "client_amount": round(liquido - saldo, 2),
        "first_due_date": "2027-01-07",
        "last_due_date": "2034-12-07",
        "monthly_effective_total_cost_rate": round(taxa_mensal + 0.2, 2),
        "annual_effective_total_cost_rate": 27.48,
        "monthly_customer_rate": taxa_mensal,
        "annual_customer_rate": 23.8721,
        "expenses": [],
        "refinancing": [
            {"proposal_operation_number": numero, "installments": []} for numero in contratos
        ],
    }


@app.post("/marketplace/proposal")
async def incluir(request: Request) -> Response:
    barrado = _barrar(request, ACCEPT_ERRO)
    if barrado:
        return barrado
    erro, registrar = _falha_programada(request)
    if erro and not registrar:
        return erro
    corpo = await request.json()
    faltando = [c for c in ("origin", "credit_condition", "payment", "client") if not corpo.get(c)]
    if faltando:
        return _erro(400, "campos obrigatórios: " + ", ".join(faltando))
    numero = str(960000001 + len(PROPOSTAS))
    PROPOSTAS[numero] = corpo
    return erro or JSONResponse({"proposal_number": numero})


@app.get("/marketplace/proposal")
async def consultar(request: Request) -> Response:
    barrado = _barrar(request, ACCEPT_CONSULTA)
    if barrado:
        return barrado
    erro, _ = _falha_programada(request)
    if erro:
        return erro
    numero = request.query_params.get("proposalNumber", "")
    proposta = PROPOSTAS.get(numero)
    if proposta is None:
        return _erro(404, "proposta não encontrada")
    return JSONResponse(
        {
            "proposal_number": numero,
            "operation_type": proposta.get("operation_type"),
            "formalization_status": "PENDENTE",
            # TODO(c6): quais são os valores de `situation` e de
            # `current_activity_description`? O manual só traz "string".
            "loan_track": {
                "situation": "AND",
                "current_activity_number": 1,
                "current_activity_description": "AGUARDA FORM DIG WEB",
            },
            "credit_condition": proposta.get("credit_condition"),
        }
    )


@app.get("/marketplace/proposal/formalization-url")
async def link(request: Request) -> Response:
    barrado = _barrar(request, ACCEPT_LINK)
    if barrado:
        return barrado
    erro, _ = _falha_programada(request)
    if erro:
        return erro
    numero = request.query_params.get("proposalNumber", "")
    if numero not in PROPOSTAS:
        return _erro(404, "proposta não encontrada")
    return JSONResponse({"url": f"http://web.c6consig.exemplo.test/{numero}", "status": "ACTIVE"})
