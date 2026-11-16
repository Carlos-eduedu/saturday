"""Simulador do motor de consultas do iCred (INSS).

Emula só o que o Saturday usa na fase 1 (decisão 0027): abrir e ler consulta,
`/saude`, `/eventos` e o webhook assinado. As formas vêm do código-fonte do
motor (ver `docs/icred.md`). Tudo em memória. A gravação (`/gravar`) entra na
fase 2.

Fora da API real: `SIMULADOR_ICRED_CENARIO` faz a consulta concluir sozinha
(`com_oferta`, `sem_oferta`, `ja_gravado`); vazio, ela fica na fila até o
`/admin/evento`.

Rodar local:
    uvicorn app:app --app-dir simuladores/icred --port 8400
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="Simulador do iCred", version="0.1.0")

CHAVE = os.environ.get("SIMULADOR_ICRED_CHAVE", "chave-do-simulador-icred")
SEGREDO = os.environ.get("SATURDAY_ICRED_WEBHOOK_SEGREDO", "segredo-do-simulador-icred")
SATURDAY_URL = os.environ.get("SIMULADOR_SATURDAY_URL", "http://api:8000")
APLICACAO = "saturday"
FUSO = timezone(timedelta(hours=-4))  # o motor usa o fuso local do servidor
VALIDADE = timedelta(minutes=15)

# Parâmetros mutáveis pelos testes (ou pelo admin).
CONFIG: dict[str, Any] = {
    "cenario": os.environ.get("SIMULADOR_ICRED_CENARIO", ""),
    "atraso_s": float(os.environ.get("SIMULADOR_ICRED_ATRASO_S", "5")),
}

CONSULTAS: dict[str, dict[str, Any]] = {}
IDEMPOTENCIA: dict[str, str] = {}
EVENTOS: list[dict[str, Any]] = []
FALHAS: list[dict[str, Any]] = []
CHAMADAS: list[tuple[str, str]] = []

# Card real de Port + Refin dos testes do motor, mais um contrato novo plausível.
PRODUTO_PORT_REFIN: dict[str, Any] = {
    "produto": "Port + Refin",
    "tipo": "port_refin",
    "banco": "Caixa",
    "saldo_devedor": 14971.87,
    "rest": 61,
    "tabela": "Normal",
    "taxa": 1.85,
    "prazo": 108,
    "parcela": 401.2,
    "liberado": 2501.92,
    "bruto": 16809.9,
    "regra": "159993",
    "pct": 5.18,
    "comissao": 870.75,
}
PRODUTO_NOVO: dict[str, Any] = {
    "produto": "Novo",
    "tipo": "novo",
    "tabela": "Normal",
    "taxa": 1.8,
    "prazo": 96,
    "parcela": 152.4,
    "liberado": 6120.35,
    "bruto": 6120.35,
    "regra": "160001",
    "pct": 4.0,
    "comissao": 244.81,
}

CENARIOS: dict[str, tuple[str, list[dict[str, Any]]]] = {
    "com_oferta": ("COM_OFERTA", [PRODUTO_NOVO]),
    "sem_oferta": ("SEM_COMISSAO", []),
    "ja_gravado": ("JA_GRAVADO", []),
}


# ------------------------------------------------------------------ suporte


def limpar() -> None:
    CONSULTAS.clear()
    IDEMPOTENCIA.clear()
    EVENTOS.clear()
    FALHAS.clear()
    CHAMADAS.clear()


def _agora() -> datetime:
    return datetime.now(FUSO).replace(microsecond=0)


def _id(prefixo: str) -> str:
    return f"{prefixo}_{_agora():%Y%m%d%H%M%S}{uuid.uuid4().hex[:8]}"


def _erro(status: int, codigo: str, mensagem: str) -> JSONResponse:
    corpo = {"erro": {"codigo": codigo, "mensagem": mensagem, "detalhes": None}}
    return JSONResponse(status_code=status, content=corpo)


def _entrada(request: Request) -> Response | None:
    """Registra a chamada, consome falha programada e confere a chave."""

    CHAMADAS.append((request.method, request.url.path))
    for falha in FALHAS:
        if falha["rota"] == request.url.path and falha["metodo"] == request.method:
            falha["vezes"] -= 1
            if falha["vezes"] <= 0:
                FALHAS.remove(falha)
            status = int(falha["status"])
            if status == 429:
                resposta = _erro(429, "limite_requisicoes", "limite por minuto")
                resposta.headers["Retry-After"] = "7"
                return resposta
            return _erro(status, "erro_interno", "falha programada")
    if not hmac.compare_digest(request.headers.get("X-API-Key", ""), CHAVE):
        return _erro(401, "chave_invalida", "chave inválida")
    return None


def _nova_consulta(corpo: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _id("c"),
        "referencia": corpo.get("referencia"),
        "aplicacao": APLICACAO,
        "acao": corpo.get("acao", "consultar"),
        "etapa": "consultar",
        "estado": "na_fila",
        "cpf": corpo["cpf"],
        "nome": corpo.get("nome"),
        "situacao": None,
        "detalhe": "",
        "comissao_rs": None,
        "produtos": [],
        "propostas": None,
        "link_enviado": None,
        "link_iflow": None,
        "link_cliente": None,
        "login": "gui",
        "criado_em": _agora().isoformat(),
        "concluido_em": None,
        "valido_ate": None,
        "webhook_estado": "pendente",
        "produtos_gravar": None,
        "oferta_mudou": None,
        "liberado_antes": None,
    }


def concluir(
    cid: str, situacao: str, produtos: list[dict[str, Any]] | None = None, detalhe: str = ""
) -> dict[str, Any]:
    """Conclui a consulta e devolve o evento `consulta.concluida` (sem entregar)."""

    consulta = CONSULTAS[cid]
    agora = _agora()
    produtos = produtos or []
    consulta.update(
        estado="concluida",
        situacao=situacao,
        detalhe=detalhe,
        produtos=produtos,
        comissao_rs=round(sum(float(p.get("comissao") or 0) for p in produtos), 2) or None,
        concluido_em=agora.isoformat(),
        valido_ate=(agora + VALIDADE).isoformat() if situacao == "COM_OFERTA" else None,
        link_cliente=(
            f"https://minha.icred.digital/resume/{uuid.uuid4()}"
            if situacao == "COM_OFERTA"
            else None
        ),
    )
    evento = {
        "id": _id("e"),
        "evento": "consulta.concluida",
        "criado_em": agora.isoformat(),
        "dados": dict(consulta),
    }
    EVENTOS.append(evento)
    return evento


def assinar(corpo: bytes, timestamp: str, segredo: str = SEGREDO) -> str:
    mac = hmac.new(segredo.encode(), timestamp.encode() + b"." + corpo, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def requisicao_webhook(
    evento: dict[str, Any], timestamp: int | None = None
) -> tuple[bytes, dict[str, str]]:
    """Corpo bruto e cabeçalhos do webhook, como o motor envia."""

    corpo = json.dumps(evento, ensure_ascii=False).encode()
    carimbo = str(int(time.time()) if timestamp is None else timestamp)
    return corpo, {
        "Content-Type": "application/json",
        "X-Icred-Evento": str(evento["evento"]),
        "X-Icred-Id": str(evento["id"]),
        "X-Icred-Timestamp": carimbo,
        "X-Icred-Assinatura": assinar(corpo, carimbo),
    }


def _entregar_http(evento: dict[str, Any]) -> int:
    corpo, cabecalhos = requisicao_webhook(evento)
    resposta = httpx.post(
        f"{SATURDAY_URL}/webhooks/icred", content=corpo, headers=cabecalhos, timeout=10
    )
    return resposta.status_code


async def _concluir_cenario(cid: str) -> None:
    await asyncio.sleep(float(CONFIG["atraso_s"]))
    situacao, produtos = CENARIOS[CONFIG["cenario"]]
    evento = concluir(cid, situacao, [dict(p) for p in produtos])
    await asyncio.to_thread(_entregar_http, evento)


# ------------------------------------------------------------------ API do motor


@app.get("/saude")
def saude() -> dict[str, Any]:
    return {"status": "ok", "versao": "1.1.0", "portabilidade_pausada": False}


@app.post("/consultas", status_code=202)
async def abrir_consulta(request: Request, tarefas: BackgroundTasks) -> Any:
    if (falha := _entrada(request)) is not None:
        return falha
    corpo = await request.json()
    if not corpo.get("cpf") or not corpo.get("telefone") or corpo.get("lgpd_ok") is not True:
        return _erro(422, "dados_invalidos", "cpf, telefone e lgpd_ok=true são obrigatórios")

    chave = request.headers.get("Idempotency-Key")
    existente = CONSULTAS.get(IDEMPOTENCIA.get(chave or "", ""))
    if existente is None:
        existente = next(
            (
                c
                for c in CONSULTAS.values()
                if c["cpf"] == corpo["cpf"] and c["estado"] in ("na_fila", "processando")
            ),
            None,
        )
    if existente is not None:
        return {
            "id": existente["id"],
            "estado": existente["estado"],
            "posicao_na_fila": 1,
            "ja_existia": True,
        }

    consulta = _nova_consulta(corpo)
    CONSULTAS[consulta["id"]] = consulta
    if chave:
        IDEMPOTENCIA[chave] = consulta["id"]
    if CONFIG["cenario"] in CENARIOS:
        tarefas.add_task(_concluir_cenario, consulta["id"])
    return {"id": consulta["id"], "estado": "na_fila", "posicao_na_fila": 1, "ja_existia": False}


@app.get("/consultas/{cid}")
def ler_consulta(cid: str, request: Request) -> Any:
    if (falha := _entrada(request)) is not None:
        return falha
    consulta = CONSULTAS.get(cid)
    if consulta is None:
        return _erro(404, "nao_encontrada", "consulta não encontrada")
    return consulta


@app.get("/eventos")
def listar_eventos(request: Request, desde: str | None = None) -> Any:
    if (falha := _entrada(request)) is not None:
        return falha
    return [e for e in EVENTOS if desde is None or e["id"] > desde]


# ------------------------------------------------------------------ admin


@app.post("/admin/evento")
async def disparar_evento(request: Request) -> dict[str, Any]:
    """Conclui uma consulta e entrega o webhook (`repetir` reenvia o mesmo evento)."""

    pedido = await request.json()
    evento = concluir(
        pedido["id"],
        pedido.get("situacao", "COM_OFERTA"),
        pedido.get("produtos"),
        pedido.get("detalhe", ""),
    )
    status = [
        await asyncio.to_thread(_entregar_http, evento)
        for _ in range(int(pedido.get("repetir", 1)))
    ]
    return {"evento": evento, "status": status}


@app.post("/admin/falha")
async def programar_falha(request: Request) -> dict[str, int]:
    pedido = await request.json()
    FALHAS.append(
        {
            "rota": pedido["rota"],
            "metodo": pedido.get("metodo", "GET"),
            "status": pedido.get("status", 500),
            "vezes": pedido.get("vezes", 1),
        }
    )
    return {"falhas": len(FALHAS)}


@app.post("/admin/config")
async def configurar(request: Request) -> dict[str, Any]:
    CONFIG.update(await request.json())
    return CONFIG


@app.post("/admin/limpar")
def admin_limpar() -> dict[str, int]:
    limpar()
    return {"consultas": 0}


@app.get("/admin/estado")
def estado() -> dict[str, Any]:
    return {"consultas": CONSULTAS, "eventos": EVENTOS, "chamadas": CHAMADAS}
