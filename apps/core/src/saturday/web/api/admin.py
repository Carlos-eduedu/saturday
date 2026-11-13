"""API do painel da equipe (`/admin/*`). Autentica por cookie de sessão.

Toda ação que muda estado exige o CSRF da sessão e grava `auditoria`. As
conversas são identificadas pelo `id` interno (UUID), nunca pelo
`conversation_id`, que no WhatsApp carrega o telefone do cliente.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, Conversa, Cota, Mensagem, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import acoes, exportacao, sessoes, supervisao
from saturday.painel.auditoria import auditar
from saturday.privacidade import MASCARAS
from saturday.settings import TZ_OPERACAO
from saturday.web.dependencies import (
    COOKIE_SESSAO,
    UsuarioLogado,
    exigir_csrf,
    exigir_fabrica,
    get_agent_service,
    get_settings,
    usuario_logado,
)
from saturday.web.eventos import Difusor, fluxo_sse

router = APIRouter(prefix="/admin", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
ComCsrf = Annotated[UsuarioLogado, Depends(exigir_csrf)]
Servico = Annotated[AgentService, Depends(get_agent_service)]

LIMITE_INBOX = 200
CampoSensivel = Literal["cpf", "telefone", "data_nascimento", "email"]


class Login(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=256)


class Envio(BaseModel):
    texto: str | None = Field(default=None, min_length=1, max_length=4096)
    modelo: str | None = None


class Transferencia(BaseModel):
    usuario_id: uuid.UUID


class Revelar(BaseModel):
    campo: CampoSensivel


def _eu(request: Request, usuario: UsuarioLogado) -> dict[str, Any]:
    segredo = get_settings(request).sessao_segredo.get_secret_value()
    return {
        "id": str(usuario.id),
        "email": usuario.email,
        "nome": usuario.nome,
        "perfil": usuario.perfil,
        "csrf": sessoes.token_csrf(segredo, usuario.token),
    }


def _recusa(exc: acoes.AcaoRecusada) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detalhe)


# ------------------------------------------------------------------ sessão


@router.post("/login")
def login(dados: Login, request: Request, response: Response, fabrica: Fabrica) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        usuario = sessoes.autenticar(sessao, dados.email, dados.senha)
        token = sessoes.abrir_sessao(sessao, usuario) if usuario else None
        logado = (
            UsuarioLogado(usuario.id, usuario.email, usuario.nome, usuario.perfil, token)
            if usuario and token
            else None
        )
    # Fora do `with`: a falha contada precisa do commit antes do 401.
    if logado is None:
        raise HTTPException(status_code=401, detail="e-mail ou senha inválidos")
    response.set_cookie(
        COOKIE_SESSAO,
        logado.token,
        max_age=int(sessoes.DURACAO_SESSAO.total_seconds()),
        httponly=True,
        secure=get_settings(request).environment not in {"dev", "pytest"},
        samesite="strict",
        path="/admin",
    )
    return _eu(request, logado)


@router.post("/logout", status_code=204)
def logout(usuario: ComCsrf, fabrica: Fabrica) -> Response:
    with abrir_sessao(fabrica) as sessao:
        sessoes.encerrar_sessao(sessao, usuario.token)
    resposta = Response(status_code=204)
    resposta.delete_cookie(COOKIE_SESSAO, path="/admin")
    return resposta


@router.get("/eu")
def eu(request: Request, usuario: Logado) -> dict[str, Any]:
    return _eu(request, usuario)


@router.get("/usuarios")
def usuarios(_usuario: Logado, fabrica: Fabrica) -> list[dict[str, Any]]:
    """Destinos possíveis de uma transferência: só quem está ativo."""

    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.scalars(
            select(UsuarioPainel).where(UsuarioPainel.ativo.is_(True)).order_by(UsuarioPainel.nome)
        ).all()
        return [
            {"id": str(u.id), "nome": u.nome, "email": u.email, "perfil": u.perfil} for u in linhas
        ]


# ------------------------------------------------------------------ conversas


def _resumo(conversa: Conversa, agora: datetime) -> dict[str, Any]:
    entrada = conversa.ultima_entrada_em
    return {
        "id": str(conversa.id),
        "canal": conversa.canal,
        "atendimento": conversa.atendimento,
        "atendente_id": str(conversa.atendente_id) if conversa.atendente_id else None,
        "telefone": MASCARAS["telefone"](conversa.telefone) if conversa.telefone else None,
        "ultima_entrada_em": entrada,
        "nao_lida": entrada is not None
        and (conversa.vista_em is None or entrada > conversa.vista_em),
        "janela_aberta": conversa.canal == "whatsapp" and janela_aberta(entrada, agora),
    }


@router.get("/conversas")
def listar_conversas(
    usuario: Logado,
    fabrica: Fabrica,
    fila: Literal["ia", "handoff", "assumida", "minhas"] | None = None,
    busca: Annotated[str | None, Query(max_length=32)] = None,
) -> list[dict[str, Any]]:
    consulta = select(Conversa)
    if fila == "minhas":
        consulta = consulta.where(
            Conversa.atendimento == "assumida", Conversa.atendente_id == usuario.id
        )
    elif fila is not None:
        consulta = consulta.where(Conversa.atendimento == fila)
    digitos = "".join(c for c in busca or "" if c.isdigit())
    if digitos:
        consulta = consulta.where(
            or_(Conversa.telefone.contains(digitos), Conversa.conversation_id == busca)
        )
    consulta = consulta.order_by(
        Conversa.ultima_entrada_em.desc().nulls_last(), Conversa.criada_em.desc()
    ).limit(LIMITE_INBOX)
    agora = datetime.now(UTC)
    with abrir_sessao(fabrica) as sessao:
        conversas = list(sessao.scalars(consulta))
        campos = supervisao.supervisao(sessao, conversas, agora)
        resumos = []
        for conversa in conversas:
            extra = campos[conversa.id]
            ultima = extra["ultima_mensagem"]
            resumos.append(
                {
                    **_resumo(conversa, agora),
                    **extra,
                    "ultima_atividade": ultima["em"] if ultima else conversa.criada_em,
                }
            )
        return supervisao.ordenar(resumos)


@router.get("/conversas/{conversa_id}")
def ver_conversa(conversa_id: uuid.UUID, _usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.get(Conversa, conversa_id)
        if conversa is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        mensagens = sessao.scalars(
            select(Mensagem)
            .where(Mensagem.conversa_id == conversa_id)
            .order_by(Mensagem.criada_em, Mensagem.id)
        ).all()
        agora = datetime.now(UTC)
        resumo = {
            **_resumo(conversa, agora),
            **supervisao.supervisao(sessao, [conversa], agora)[conversa.id],
        }
        historico = [
            {
                "id": m.id,
                "direcao": m.direcao,
                "autor": m.autor,
                "usuario_id": str(m.usuario_id) if m.usuario_id else None,
                "conteudo": m.conteudo,
                "status_entrega": m.status_entrega,
                "criada_em": m.criada_em,
                "anexos": [{"mime_type": a.get("mime_type")} for a in m.anexos or []],
            }
            for m in mensagens
        ]
        conversa.vista_em = func.now()
    # Modelo é da Meta; a Evolution só manda texto (decisão 0009).
    modelos = list(acoes.MODELOS_DO_PAINEL) if conversa.canal == "whatsapp" else []
    return {**resumo, "mensagens": historico, "modelos": modelos}


@router.get("/conversas/{conversa_id}/exportar")
def exportar(
    conversa_id: uuid.UUID, usuario: Logado, fabrica: Fabrica, service: Servico
) -> Response:
    """A conversa inteira em Markdown, para levar a outro lugar (inclusive a uma IA)."""

    agora = datetime.now(UTC)
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.get(Conversa, conversa_id)
        if conversa is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        supervisionado = supervisao.supervisao(sessao, [conversa], agora)[conversa.id]
        retrato = exportacao.carregar(
            sessao,
            conversa,
            ficha=_ficha(conversa, _estado(conversa, service)),
            supervisao=supervisionado,
            gestor=usuario.gestor,
            agora=agora,
            exportado_por=usuario.email,
        )
        # O arquivo leva a conversa para fora do painel: fica registrado quem levou.
        auditar(sessao, usuario.id, "exportar", str(conversa_id))
    return Response(
        content=exportacao.conversa_em_markdown(retrato),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="conversa-{conversa_id}.md"',
            "Cache-Control": "private, no-store",
        },
    )


def _executar(
    fabrica: sessionmaker[Session],
    conversa_id: uuid.UUID,
    acao: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        with acoes.conversa_travada(fabrica, conversa_id) as (sessao, conversa):
            return acao(sessao, conversa, *args, **kwargs)
    except acoes.AcaoRecusada as exc:
        raise _recusa(exc) from exc


@router.post("/conversas/{conversa_id}/assumir", status_code=204)
def assumir(conversa_id: uuid.UUID, usuario: ComCsrf, fabrica: Fabrica) -> Response:
    _executar(fabrica, conversa_id, acoes.assumir, usuario.id, usuario.gestor)
    return Response(status_code=204)


@router.post("/conversas/{conversa_id}/devolver", status_code=204)
def devolver(
    conversa_id: uuid.UUID, usuario: ComCsrf, fabrica: Fabrica, service: Servico
) -> Response:
    conversation_id = _executar(fabrica, conversa_id, _devolver, usuario)
    # O checkpoint fica fora da transação do banco: quem decide quem responde
    # é `conversas`, já gravado; aqui só se zera o handoff do grafo.
    service.limpar_handoff(conversation_id)
    return Response(status_code=204)


def _devolver(sessao: Session, conversa: Conversa, usuario: UsuarioLogado) -> str:
    acoes.devolver(sessao, conversa, usuario.id, usuario.gestor)
    return conversa.conversation_id


@router.post("/conversas/{conversa_id}/desfazer", status_code=204)
def desfazer(conversa_id: uuid.UUID, usuario: ComCsrf, fabrica: Fabrica) -> Response:
    _executar(fabrica, conversa_id, acoes.desfazer, usuario.id)
    return Response(status_code=204)


@router.post("/conversas/{conversa_id}/transferir", status_code=204)
def transferir(
    conversa_id: uuid.UUID, dados: Transferencia, usuario: ComCsrf, fabrica: Fabrica
) -> Response:
    _executar(fabrica, conversa_id, acoes.transferir, usuario.id, usuario.gestor, dados.usuario_id)
    return Response(status_code=204)


@router.post("/conversas/{conversa_id}/mensagens", status_code=201)
def enviar(
    conversa_id: uuid.UUID, dados: Envio, usuario: ComCsrf, fabrica: Fabrica
) -> dict[str, int]:
    mensagem_id = _executar(
        fabrica, conversa_id, acoes.enviar, usuario.id, texto=dados.texto, modelo=dados.modelo
    )
    return {"mensagem_id": mensagem_id}


# ------------------------------------------------------------------ ficha


def _estado(conversa: Conversa, service: AgentService) -> dict[str, Any]:
    return service.estado_atual(service.config(conversa.conversation_id))


def _dados_clt(estado: dict[str, Any]) -> dict[str, Any]:
    """O que o ramo CLT coletou; o INSS guarda em ``cliente``."""

    return dict((estado.get("clt") or {}).get("dados") or {})


def _dados_sensiveis(conversa: Conversa, estado: dict[str, Any]) -> dict[str, str]:
    cliente = estado.get("cliente") or {}
    clt = _dados_clt(estado)
    valores = {
        "telefone": conversa.telefone,
        "cpf": cliente.get("cpf") or clt.get("cpf"),
        "data_nascimento": cliente.get("data_nascimento") or clt.get("nascimento"),
        "email": clt.get("email"),
    }
    return {campo: str(valor) for campo, valor in valores.items() if valor}


def _ficha(conversa: Conversa, estado: dict[str, Any]) -> dict[str, Any]:
    """A ficha como a tela e a exportação a mostram: só com dado mascarado."""

    cliente = estado.get("cliente") or {}
    sensiveis = _dados_sensiveis(conversa, estado)
    return {
        "nome": cliente.get("nome") or _dados_clt(estado).get("nome"),
        "dados": {campo: MASCARAS[campo](valor) for campo, valor in sensiveis.items()},
        "uf": cliente.get("uf"),
        "publico": estado.get("publico"),
        "handoff_reason": estado.get("handoff_reason"),
        "portabilidade": estado.get("portability_result"),
    }


@router.get("/conversas/{conversa_id}/ficha")
def ficha(
    conversa_id: uuid.UUID, _usuario: Logado, fabrica: Fabrica, service: Servico
) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.get(Conversa, conversa_id)
        if conversa is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        return _ficha(conversa, _estado(conversa, service))


@router.post("/conversas/{conversa_id}/revelar")
def revelar(
    conversa_id: uuid.UUID,
    dados: Revelar,
    usuario: ComCsrf,
    fabrica: Fabrica,
    service: Servico,
) -> dict[str, str]:
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.get(Conversa, conversa_id)
        if conversa is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        valor = _dados_sensiveis(conversa, _estado(conversa, service)).get(dados.campo)
        if valor is None:
            raise HTTPException(status_code=404, detail="dado não informado")
        # Na mesma transação: sem a linha de auditoria, o dado não sai.
        auditar(sessao, usuario.id, f"revelar:{dados.campo}", str(conversa_id))
    return {"campo": dados.campo, "valor": valor}


# ------------------------------------------------------------------ alertas e cota


@router.get("/alertas")
def alertas(_usuario: Logado, fabrica: Fabrica, abertos: bool = True) -> list[dict[str, Any]]:
    consulta = select(Alerta).order_by(Alerta.criado_em.desc()).limit(LIMITE_INBOX)
    if abertos:
        consulta = consulta.where(Alerta.resolvido_em.is_(None))
    with abrir_sessao(fabrica) as sessao:
        return [
            {
                "id": a.id,
                "tipo": a.tipo,
                "conversa_id": str(a.conversa_id) if a.conversa_id else None,
                "detalhe": a.detalhe,
                "criado_em": a.criado_em,
                "resolvido_em": a.resolvido_em,
            }
            for a in sessao.scalars(consulta)
        ]


@router.post("/alertas/{alerta_id}/resolver", status_code=204)
def resolver_alerta(alerta_id: int, usuario: ComCsrf, fabrica: Fabrica) -> Response:
    with abrir_sessao(fabrica) as sessao:
        resolvido = sessao.execute(
            update(Alerta)
            .where(Alerta.id == alerta_id, Alerta.resolvido_em.is_(None))
            .values(resolvido_por=usuario.id, resolvido_em=func.now())
            .returning(Alerta.id)
        ).scalar_one_or_none()
        if resolvido is not None:
            auditar(sessao, usuario.id, "resolver_alerta", str(alerta_id))
            repositorios.notificar(sessao, "alerta", alerta=alerta_id)
    return Response(status_code=204)


@router.get("/cota")
def cota(request: Request, _usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    settings = get_settings(request)
    hoje = datetime.now(ZoneInfo(TZ_OPERACAO)).date()
    with abrir_sessao(fabrica) as sessao:
        base = select(func.coalesce(func.sum(Cota.usadas), 0)).where(Cota.parceiro == "granatech")
        mes = sessao.scalar(base.where(Cota.dia >= date(hoje.year, hoje.month, 1)))
        dia = sessao.scalar(base.where(Cota.dia == hoje))
    return {
        "mes": {"usadas": int(mes or 0), "teto": settings.granatech_cota_mensal},
        "dia": {"usadas": int(dia or 0), "teto": settings.granatech_cota_diaria},
    }


# ------------------------------------------------------------------ mídia


@router.get("/midia/{mensagem_id}/{indice}")
def midia(
    mensagem_id: int, indice: int, _usuario: Logado, fabrica: Fabrica, service: Servico
) -> Response:
    """Passa o arquivo pela API: URL pré-assinada vazaria se fosse copiada."""

    with abrir_sessao(fabrica) as sessao:
        mensagem = sessao.get(Mensagem, mensagem_id)
        anexos = (mensagem.anexos or []) if mensagem else []
    if not 0 <= indice < len(anexos) or service.storage is None:
        raise HTTPException(status_code=404, detail="anexo não encontrado")
    anexo = anexos[indice]
    try:
        dados = service.storage.ler(str(anexo["chave"]))
    except Exception as exc:
        # A retenção apaga o arquivo e mantém a mensagem.
        raise HTTPException(status_code=404, detail="anexo não encontrado") from exc
    return Response(
        content=dados,
        media_type=str(anexo.get("mime_type") or "application/octet-stream"),
        headers={"Cache-Control": "private, no-store"},
    )


# ------------------------------------------------------------------ tempo real


@router.get("/eventos")
async def eventos(request: Request, _usuario: Logado) -> StreamingResponse:
    difusor: Difusor | None = getattr(request.app.state, "difusor", None)
    if difusor is None:
        raise HTTPException(status_code=503, detail="tempo real indisponível")
    fila = difusor.assinar()

    async def corpo() -> AsyncIterator[str]:
        try:
            async for evento in fluxo_sse(fila):
                if await request.is_disconnected():
                    break
                yield evento
        finally:
            difusor.cancelar(fila)

    return StreamingResponse(
        corpo(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
