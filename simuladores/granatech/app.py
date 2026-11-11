"""Simulador da API de parceiros da Granatech (consignado CLT).

Emula só o que o Saturday usa, com as respostas observadas na api-dev (ver
AGENTS.md, "Dados do simulador da Granatech"). Tudo em memória. O admin
dispara eventos de webhook (inclusive duplicados e fora de ordem) e programa
falhas: 401, 500 ou timeout, com a opção de executar a operação antes de falhar
(o caso "incerto" de uma proposta).

Formatos ainda não confirmados pela Granatech (listagens, resposta do POST de
proposta) seguem uma forma plausível e estão marcados com TODO(granatech).

Rodar local:
    uvicorn app:app --app-dir simuladores/granatech --port 8200
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Simulador da Granatech", version="0.1.0")

PREFIXO = "/api-consignado/v1"
CHAVE = os.environ.get("SIMULADOR_GRANATECH_CHAVE", "chave-do-simulador")
WEBHOOK_TOKEN = os.environ.get("SATURDAY_GRANATECH_WEBHOOK_TOKEN", "token-do-simulador")
SATURDAY_URL = os.environ.get("SIMULADOR_SATURDAY_URL", "http://api:8000")

# Parâmetros mutáveis pelos testes (ou pelo admin).
CONFIG: dict[str, Any] = {
    "atraso_detalhe_s": float(os.environ.get("SIMULADOR_ATRASO_DETALHE_S", "8")),
    "expira_em": "1h",
    "timeout_s": 30.0,
}

TOKENS: dict[str, float] = {}
CONSULTAS: dict[str, dict[str, Any]] = {}
PROPOSTAS: dict[str, dict[str, Any]] = {}
FALHAS: list[dict[str, Any]] = []
LOGINS: list[float] = []
CHAMADAS: list[tuple[str, str]] = []

# Resultado da dev: AAA36, 36 × R$ 300.
BASE_PARCELA = 300.0
BASE_PRAZO = 36
BASE = {
    "liberado": 4619.53,
    "iof": 175.28,
    "seguro": 503.32,
    "financiado": 5298.13,
}
TAXA = 0.04

PESSOA = {
    "name": "CLIENTE DE TESTE DA SILVA",
    "document": "00189004967",
    "birth_date": "1990-05-15",
    "age": 36,
    "gender": "M",
    "mother_name": "MAE DE TESTE DA SILVA",
    "civil_status": "SOLTEIRO",
    "email": "cliente@exemplo.com",
    "phone_number": "11987654321",
    "address": {
        "zip_code": "01001000",
        "address_name": "PRACA DA SE",
        "number": "100",
        "complement": "",
        "district": "SE",
        "city": "SAO PAULO",
        "uf": "SP",
    },
}

EMPREGADORES = [
    ("Prime Tech LTDA", "12345678000190"),
    ("EMPREGADOR MOCK LTDA", "98765432000110"),
]
PRODUTOS = [("AA17", 17), ("AA25", 25), ("AAA36", 36), ("AAA48", 48)]


# ------------------------------------------------------------------ suporte


def limpar() -> None:
    TOKENS.clear()
    CONSULTAS.clear()
    PROPOSTAS.clear()
    FALHAS.clear()
    LOGINS.clear()
    CHAMADAS.clear()


def _erro(status: int, mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": mensagem})


def _segundos(expira_em: str) -> float:
    if expira_em.endswith("h"):
        return float(expira_em[:-1]) * 3600
    if expira_em.endswith("m"):
        return float(expira_em[:-1]) * 60
    if expira_em.endswith("s"):
        return float(expira_em[:-1])
    return 3600.0


async def _falha_programada(request: Request) -> tuple[Response | None, bool]:
    """Consome a primeira falha cuja rota casa com o caminho.

    Devolve a resposta de erro e se a operação deve ser executada mesmo assim
    (``registrar``: a Granatech fez, mas a resposta não chegou).
    """

    caminho = request.url.path
    for falha in FALHAS:
        if falha.get("metodo", request.method) != request.method:
            continue
        if not caminho.startswith(PREFIXO + str(falha.get("rota", ""))):
            continue
        falha["vezes"] = int(falha.get("vezes", 1)) - 1
        if falha["vezes"] <= 0:
            FALHAS.remove(falha)
        if falha.get("status") == "timeout":
            await asyncio.sleep(float(CONFIG["timeout_s"]))
            return _erro(504, "timeout simulado"), bool(falha.get("registrar"))
        return _erro(int(falha.get("status", 500)), "falha simulada"), bool(falha.get("registrar"))
    return None, False


def _autorizado(request: Request) -> bool:
    cabecalho = request.headers.get("authorization", "")
    token = cabecalho.removeprefix("Bearer ").strip()
    expira = TOKENS.get(token)
    return expira is not None and expira > time.time()


async def _entrada(request: Request) -> tuple[Response | None, bool]:
    """Registro da chamada, falha programada e autenticação, nessa ordem."""

    CHAMADAS.append((request.method, request.url.path))
    falha, registrar = await _falha_programada(request)
    if falha is not None and not registrar:
        return falha, False
    if not _autorizado(request):
        return _erro(401, "token inválido ou expirado"), False
    return falha, registrar


# ------------------------------------------------------------------ autenticação


@app.post("/api/v1/auth/login", status_code=201)
async def login(request: Request) -> Any:
    falha, _ = await _falha_programada(request)
    if falha is not None:
        return falha
    corpo = await request.json()
    if corpo.get("chave_api") != CHAVE:
        return _erro(401, "chave inválida")
    token = uuid.uuid4().hex
    TOKENS[token] = time.time() + _segundos(str(CONFIG["expira_em"]))
    LOGINS.append(time.time())
    return {"token": token, "expira_em": CONFIG["expira_em"]}


# ------------------------------------------------------------------ consulta


def _margens() -> list[dict[str, Any]]:
    margens = []
    for indice, (nome, documento) in enumerate(EMPREGADORES, start=1):
        margens.append(
            {
                "id": f"margem-{indice}",
                "margem": "1.500,00",
                "nome_empregador": nome,
                "documento_empregador": documento,
                "elegivel_empregador": True,
                "produtos": [
                    {
                        "id": codigo,
                        "nome": codigo,
                        "parcelas": [prazo],
                        "taxa_mensal": 4,
                        "seguro": True,
                        "margem": "1.500,00",
                        "limite_minimo": "500,00",
                        "limite_maximo": "50.000,00",
                        "id_empresa_seguro": 7,
                        "id_cobertura_seguro": 21,
                    }
                    for codigo, prazo in PRODUTOS
                ],
            }
        )
    return margens


def _pronta(consulta: dict[str, Any]) -> bool:
    pronta_em = consulta.get("pronta_em")
    return pronta_em is not None and time.time() >= pronta_em


@app.get(PREFIXO + "/consulta-saldo/usuario")
async def listar_consultas(request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    cpf = request.query_params.get("valor_filtro", "")
    # TODO(granatech): formato real da listagem por CPF.
    return {
        "data": [
            {
                "id": identificador,
                "cpf": consulta["cpf"],
                "status": consulta["status"],
                "created_at": consulta["criada_em"],
            }
            for identificador, consulta in CONSULTAS.items()
            if consulta["cpf"] == cpf
        ]
    }


@app.get(PREFIXO + "/consulta-saldo/{id_consulta}")
async def detalhe_consulta(id_consulta: str, request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    consulta = CONSULTAS.get(id_consulta)
    if consulta is None:
        return _erro(404, "consulta não encontrada")
    if not _pronta(consulta):
        return {"id": id_consulta, "margens": [], "pessoa_natural": None}
    return {
        "id": id_consulta,
        "margens": _margens(),
        "pessoa_natural": {**PESSOA, "document": consulta["cpf"]},
    }


@app.get(PREFIXO + "/consulta-saldo")
async def abrir_consulta(request: Request) -> Any:
    falha, registrar = await _entrada(request)
    if falha is not None and not registrar:
        return falha
    cpf = request.query_params.get("cpf", "")
    telefone = request.query_params.get("telefone", "")
    if len(cpf) != 11 or len(telefone) != 11 or not request.query_params.get("nome"):
        return _erro(400, "cpf, nome e telefone (11 dígitos) são obrigatórios")
    identificador = uuid.uuid4().hex
    CONSULTAS[identificador] = {
        "cpf": cpf,
        "status": "AWAITING_CLIENT_AUTHORIZATION",
        "criada_em": date.today().isoformat(),
        "pronta_em": None,
    }
    if falha is not None:
        return falha
    return {
        "id": identificador,
        "status": "AWAITING_CLIENT_AUTHORIZATION",
        "link_termo_consentimento": f"https://termo.simulador/{identificador}",
    }


@app.post(PREFIXO + "/termo-consentimento", status_code=201)
async def termo(request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    corpo = await request.json()
    faltando = [c for c in ("cpf", "email", "nome", "telefone", "id_consulta") if not corpo.get(c)]
    if faltando:
        return _erro(400, "campos obrigatórios: " + ", ".join(faltando))
    consulta = CONSULTAS.get(str(corpo["id_consulta"]))
    if consulta is None:
        return _erro(404, "consulta não encontrada")
    consulta["pronta_em"] = time.time() + float(CONFIG["atraso_detalhe_s"])
    consulta["status"] = "PROCESSING"
    return {"success": True, "message": "Termo de consentimento criado com sucesso"}


# ------------------------------------------------------------------ simulação


def _fator_prazo(prazo: int) -> float:
    """Valor presente de uma série de parcelas, relativo ao prazo da dev."""

    def presente(n: int) -> float:
        return float((1 - (1 + TAXA) ** -n) / TAXA)

    return presente(prazo) / presente(BASE_PRAZO)


@app.get(PREFIXO + "/simulacao/{id_produto}")
async def simular(id_produto: str, request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    parametros = request.query_params
    try:
        parcela = float(parametros["valor_parcela"])
        prazo = int(parametros["numero_parcelas"])
    except KeyError, ValueError:
        return _erro(400, "valor_parcela e numero_parcelas são obrigatórios")
    if not parametros.get("id_margem"):
        return _erro(400, "id_margem é obrigatório")

    escala = parcela / BASE_PARCELA * _fator_prazo(prazo)
    valores = {chave: round(valor * escala, 2) for chave, valor in BASE.items()}
    vencimento = date.today() + timedelta(days=40)
    # Na dev, `seguro=false` é ignorado: só volta o bloco com seguro.
    return {
        "resultado_da_simulacao_com_seguro": {
            "valor_solicitado": valores["liberado"],
            "valor_parcela": parcela,
            "numero_parcelas": prazo,
            "taxa_mensal": 4.0,
            "taxa_anual": 60.1,
            "cet_mensal": 4.9848,
            "cet_anual": 79.27,
            "valor_iof": valores["iof"],
            "valor_seguro": valores["seguro"],
            "valor_total_financiado": valores["financiado"],
            "valor_total_divida": round(parcela * prazo, 2),
            "parcelas": [{"dt_vencimento": vencimento.isoformat()}],
            "id_empregador": 501,
            "info_seguradora": {
                "id_externo": "SM-100000721-6",
                "processadora": "BMP_MOCK",
                "produto": id_produto,
            },
        }
    }


# ------------------------------------------------------------------ proposta


@app.post(PREFIXO + "/propostas", status_code=201)
async def criar_proposta(request: Request) -> Any:
    falha, registrar = await _entrada(request)
    if falha is not None and not registrar:
        return falha
    corpo = await request.json()
    consulta = CONSULTAS.get(str(corpo.get("id_consulta")))
    financeiras = corpo.get("informacoesFinanceira") or [{}]
    if consulta is None:
        return _erro(400, "id_consulta inválido")
    identificador = uuid.uuid4().hex
    PROPOSTAS[identificador] = {
        "id": identificador,
        "id_consulta": corpo.get("id_consulta"),
        "cpf": consulta["cpf"],
        "valor_parcela": financeiras[0].get("valor_parcela"),
        "numero_parcelas": financeiras[0].get("numero_parcelas"),
        "status": "PENDING_CONFIRMATION",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if falha is not None:
        return falha
    # TODO(granatech): formato real da resposta (id, id_proposta ou data.id).
    return {"id": identificador}


@app.get(PREFIXO + "/propostas/lista")
async def listar_propostas(request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    termo_busca = request.query_params.get("termo_busca", "")
    # TODO(granatech): formato real da listagem de propostas.
    return {"data": [p for p in PROPOSTAS.values() if termo_busca in (p["cpf"], p["id"])]}


@app.get(PREFIXO + "/propostas/{id_proposta}")
async def detalhe_proposta(id_proposta: str, request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    proposta = PROPOSTAS.get(id_proposta)
    if proposta is None:
        return _erro(404, "proposta não encontrada")
    return {
        **proposta,
        "url_seguranca_identidade": f"https://biometria.simulador/{id_proposta}",
    }


@app.post(PREFIXO + "/propostas/{id_proposta}/dados-tomador")
async def dados_tomador(id_proposta: str, request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    if id_proposta not in PROPOSTAS:
        return _erro(404, "proposta não encontrada")
    return {"success": True}


@app.post(PREFIXO + "/propostas/{id_proposta}/cancelar")
async def cancelar(id_proposta: str, request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    proposta = PROPOSTAS.get(id_proposta)
    if proposta is None:
        return _erro(404, "proposta não encontrada")
    proposta["status"] = "CANCELED_BY_CLIENT"
    return {"success": True}


@app.get(PREFIXO + "/bancos")
async def bancos(request: Request) -> Any:
    falha, _ = await _entrada(request)
    if falha is not None:
        return falha
    return [
        {"codigo": "001", "nome": "Banco do Brasil", "habilitado": True},
        {"codigo": "341", "nome": "Itaú", "habilitado": True},
        {"codigo": "999", "nome": "Banco Desligado", "habilitado": False},
    ]


# ------------------------------------------------------------------ admin


def montar_evento(pedido: dict[str, Any]) -> dict[str, Any]:
    """Payload de webhook no formato que a Granatech envia."""

    if str(pedido.get("tipo", "")).lower() == "proposta":
        return {
            "tipo": "proposta",
            "status_da_proposta": pedido.get("status"),
            "tipo_notificacao": pedido.get("tipo_notificacao"),
            "id_proposta": pedido.get("id"),
            "informacoes": pedido.get("informacoes"),
        }
    consulta = CONSULTAS.get(str(pedido.get("id")), {})
    if pedido.get("status") == "SUCCESS" and consulta:
        consulta["pronta_em"] = time.time()
        consulta["status"] = "SUCCESS"
    return {
        "id_solicitacao": pedido.get("id"),
        "id_proposta": None,
        "cpf": consulta.get("cpf"),
        "status": pedido.get("status"),
        "user_id": 1,
        "corban_id": 1,
        "tipo": "CONSULTA",
    }


def _entregar_http(evento: dict[str, Any]) -> int:
    destino = f"{SATURDAY_URL.rstrip('/')}/webhooks/granatech"
    resposta = httpx.post(
        destino, json=evento, headers={"x-webhook-token": WEBHOOK_TOKEN}, timeout=10.0
    )
    return resposta.status_code


# Os testes do Saturday trocam por uma função que chama a API em processo.
entregar: Callable[[dict[str, Any]], int] = _entregar_http


@app.post("/admin/evento")
async def disparar_evento(request: Request) -> dict[str, Any]:
    """Um evento (`tipo`, `id`, `status`…) com `repetir`, ou `eventos` em lote.

    Com `ordem: "invertida"`, o lote sai do último para o primeiro.
    """

    corpo = await request.json()
    pedidos = list(corpo.get("eventos") or [corpo])
    if corpo.get("ordem") == "invertida":
        pedidos.reverse()
    respostas = []
    for pedido in pedidos:
        evento = montar_evento(pedido)
        for _ in range(int(pedido.get("repetir", 1))):
            respostas.append(entregar(evento))
    return {"entregues": len(respostas), "saturday_status": respostas}


@app.post("/admin/falha")
async def programar_falha(request: Request) -> dict[str, int]:
    """`{rota, status: 401|500|"timeout", vezes, metodo, registrar}`."""

    FALHAS.append(await request.json())
    return {"programadas": len(FALHAS)}


@app.post("/admin/config")
async def configurar(request: Request) -> dict[str, Any]:
    CONFIG.update(await request.json())
    return CONFIG


@app.post("/admin/limpar")
def admin_limpar() -> dict[str, int]:
    limpar()
    return {"ok": 1}


@app.get("/admin/estado")
def estado() -> dict[str, Any]:
    return {
        "consultas": CONSULTAS,
        "propostas": PROPOSTAS,
        "logins": len(LOGINS),
        "chamadas": CHAMADAS,
    }
