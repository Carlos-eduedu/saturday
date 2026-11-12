"""Tela Canais do painel (`/admin/canais`), só para gestor (decisão 0010).

Números da Meta só para leitura; instâncias da Evolution geridas aqui: a
própria Evolution diz quais existem, e o Saturday guarda só o telefone fixado.
Toda ação exige CSRF e, quando a Evolution aceita, grava `auditoria`.
"""

from __future__ import annotations

import hmac
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.evolution.cliente import (
    CONFIGURACOES,
    EVENTOS_WEBHOOK,
    EvolutionClient,
    Qr,
)
from saturday.canais.whatsapp.cliente import ErroPermanente, ErroWhatsApp
from saturday.dados import instancias
from saturday.dados.modelos import Conversa
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel.auditoria import auditar
from saturday.privacidade import mascarar_telefone
from saturday.settings import Settings
from saturday.web.dependencies import (
    UsuarioLogado,
    exigir_csrf,
    exigir_fabrica,
    get_settings,
    usuario_logado,
)

router = APIRouter(prefix="/admin/canais", tags=["painel"])

NOME = re.compile(r"^[a-z0-9-]{3,32}$")
DIAS_DE_USO = 7


def get_cliente_evolution(request: Request) -> EvolutionClient:
    settings = get_settings(request)
    if not settings.evolution_ativo:
        raise HTTPException(status_code=404, detail="canal Evolution desligado")
    return EvolutionClient(request.app.state.http, settings)


def _gestor(usuario: UsuarioLogado) -> UsuarioLogado:
    if not usuario.gestor:
        raise HTTPException(status_code=403, detail="só gestor")
    return usuario


def gestor_logado(usuario: Annotated[UsuarioLogado, Depends(usuario_logado)]) -> UsuarioLogado:
    return _gestor(usuario)


def gestor_com_csrf(usuario: Annotated[UsuarioLogado, Depends(exigir_csrf)]) -> UsuarioLogado:
    return _gestor(usuario)


Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Gestor = Annotated[UsuarioLogado, Depends(gestor_logado)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]
Evolution = Annotated[EvolutionClient, Depends(get_cliente_evolution)]


class NovaInstancia(BaseModel):
    nome: str = Field(min_length=3, max_length=32)


def _qr(qr: Qr) -> dict[str, Any]:
    return {"qr": qr.imagem, "estado": qr.estado}


def _falha(exc: ErroWhatsApp) -> HTTPException:
    """A Evolution recusou (permanente) ou não respondeu (o resto)."""

    if isinstance(exc, ErroPermanente):
        return HTTPException(status_code=409, detail=f"a Evolution recusou: {exc}")
    return HTTPException(status_code=502, detail="a Evolution não respondeu")


def _conversas_recentes(sessao: Session) -> dict[str, int]:
    """Conversas por instância com entrada nos últimos 7 dias."""

    desde = datetime.now(UTC) - timedelta(days=DIAS_DE_USO)
    linhas = sessao.execute(
        select(Conversa.phone_number_id, func.count())
        .where(Conversa.canal == "evolution", Conversa.ultima_entrada_em >= desde)
        .group_by(Conversa.phone_number_id)
    ).all()
    return {str(nome): int(total) for nome, total in linhas}


@router.get("")
def listar(request: Request, _usuario: Gestor, fabrica: Fabrica) -> dict[str, Any]:
    settings = get_settings(request)
    meta = [{"phone_number_id": numero} for numero in settings.whatsapp_numeros]
    resposta: dict[str, Any] = {
        "meta": meta,
        "evolution": {"ativo": settings.evolution_ativo, "instancias": [], "erro": None},
    }
    if not settings.evolution_ativo:
        return resposta

    try:
        estados = EvolutionClient(request.app.state.http, settings).listar()
    except ErroWhatsApp:
        # A tela continua de pé; só a lista da Evolution fica de fora.
        resposta["evolution"]["erro"] = "a Evolution não respondeu"
        return resposta

    with abrir_sessao(fabrica) as sessao:
        recentes = _conversas_recentes(sessao)
        fixados = instancias.telefones(sessao)
    resposta["evolution"]["instancias"] = [
        {
            "nome": e.nome,
            "estado": e.estado,
            "telefone": mascarar_telefone(e.telefone or fixados.get(e.nome, "")),
            "conversas_7_dias": recentes.get(e.nome, 0),
        }
        for e in sorted(estados, key=lambda e: e.nome)
    ]
    return resposta


@router.post("/evolution", status_code=201)
def criar(
    dados: NovaInstancia, usuario: GestorCsrf, fabrica: Fabrica, cliente: Evolution
) -> dict[str, Any]:
    if not NOME.match(dados.nome):
        raise HTTPException(status_code=422, detail="nome: letras minúsculas, números e hífen")
    try:
        qr = cliente.criar_instancia(dados.nome)
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc
    with abrir_sessao(fabrica) as sessao:
        auditar(sessao, usuario.id, "canal_criar", dados.nome)
    return _qr(qr)


@router.post("/evolution/{nome}/conectar")
def conectar(
    nome: str, usuario: GestorCsrf, fabrica: Fabrica, cliente: Evolution
) -> dict[str, Any]:
    """Reaplica webhook e configurações e devolve o QR; recusa se já conectada."""

    try:
        if any(e.nome == nome and e.estado == "open" for e in cliente.listar()):
            raise HTTPException(status_code=409, detail="instância já conectada")
        cliente.configurar(nome)
        qr = cliente.conectar(nome)
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc
    with abrir_sessao(fabrica) as sessao:
        auditar(sessao, usuario.id, "canal_conectar", nome)
    return _qr(qr)


@router.get("/evolution/{nome}/qr")
def qr_atual(nome: str, _usuario: Gestor, cliente: Evolution) -> dict[str, Any]:
    """Renovado pela tela a cada poucos segundos até conectar."""

    try:
        return _qr(cliente.conectar(nome))
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc


def _situacao_do_token(cabecalhos: Any, esperado: str) -> str:
    """`confere`, `diferente` ou `ausente`; o valor nunca sai daqui."""

    if not isinstance(cabecalhos, dict):
        return "ausente"
    recebido = next(
        (str(v) for k, v in cabecalhos.items() if str(k).lower() == "x-webhook-token"), ""
    )
    if not recebido:
        return "ausente"
    return "confere" if hmac.compare_digest(recebido, esperado) else "diferente"


def _detalhes(
    webhook: dict[str, Any], atuais: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    """Webhook e configurações da instância ao lado do que o Saturday aplica.

    Só campos conhecidos saem para o painel: os cabeçalhos levam o token, e as
    configurações da Evolution têm campos que não nos dizem respeito.
    """

    eventos = [str(e) for e in webhook.get("events") or [] if isinstance(e, str)]
    url_esperada = settings.evolution_webhook_url
    conferencia = _situacao_do_token(
        webhook.get("headers"), settings.evolution_webhook_token.get_secret_value()
    )
    configuracoes = [
        {"nome": nome, "atual": atuais.get(nome), "esperado": esperado}
        for nome, esperado in CONFIGURACOES.items()
    ]

    divergencias: list[str] = []
    if not webhook:
        divergencias.append("Nenhum webhook configurado na instância.")
    else:
        if webhook.get("enabled") is not True:
            divergencias.append("Webhook desligado.")
        if webhook.get("url") != url_esperada:
            divergencias.append("URL do webhook diferente da esperada.")
        faltando = [e for e in EVENTOS_WEBHOOK if e not in eventos]
        if faltando:
            divergencias.append(f"Eventos que faltam: {', '.join(faltando)}.")
        if conferencia != "confere":
            divergencias.append(f"Token do webhook {conferencia}.")
        if webhook.get("webhookByEvents") is True:
            divergencias.append("Webhook por evento ligado: a Evolution muda a URL por evento.")
    divergencias += [
        f"Configuração {c['nome']} diferente da esperada."
        for c in configuracoes
        if atuais and c["atual"] != c["esperado"]
    ]

    return {
        "webhook": {
            "configurado": bool(webhook),
            "ativo": webhook.get("enabled") is True,
            "url": webhook.get("url") or "",
            "url_esperada": url_esperada,
            "eventos": eventos,
            "eventos_esperados": EVENTOS_WEBHOOK,
            "por_evento": webhook.get("webhookByEvents") is True,
            "base64": webhook.get("webhookBase64") is True,
            "autenticacao": conferencia,
        },
        "configuracoes": configuracoes if atuais else [],
        "divergencias": divergencias,
    }


@router.get("/evolution/{nome}/detalhes")
def detalhes(nome: str, request: Request, _usuario: Gestor, cliente: Evolution) -> dict[str, Any]:
    """O que a Evolution tem gravado para a instância, comparado com o esperado."""

    try:
        webhook = cliente.webhook_atual(nome)
        atuais = cliente.configuracoes_atuais(nome)
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc
    return _detalhes(webhook, atuais, get_settings(request))


@router.post("/evolution/{nome}/desconectar", status_code=204)
def desconectar(nome: str, usuario: GestorCsrf, fabrica: Fabrica, cliente: Evolution) -> Response:
    try:
        cliente.desconectar(nome)
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc
    with abrir_sessao(fabrica) as sessao:
        auditar(sessao, usuario.id, "canal_desconectar", nome)
    return Response(status_code=204)


@router.delete("/evolution/{nome}", status_code=204)
def apagar(nome: str, usuario: GestorCsrf, fabrica: Fabrica, cliente: Evolution) -> Response:
    try:
        cliente.apagar(nome)
    except ErroWhatsApp as exc:
        raise _falha(exc) from exc
    with abrir_sessao(fabrica) as sessao:
        # O nome fica livre para outro telefone.
        instancias.soltar(sessao, nome)
        auditar(sessao, usuario.id, "canal_apagar", nome)
    return Response(status_code=204)
