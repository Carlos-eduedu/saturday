"""Aba Granatech do painel (`/admin/granatech`).

Atendente e gestor veem consultas e propostas; só o gestor age, e toda ação
grava a auditoria antes de chamar o banco (decisão 0013). Abrir consulta,
simular e criar proposta não existem aqui: dependem do SIM do cliente, que só
vem pela conversa. Ação que muda a jornada roda como turno de sistema; cancelar
e corrigir a conta só chamam a Granatech, e a jornada muda quando o webhook
chegar.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Annotated, Any, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService, Jornada
from saturday.bancos.granatech import homologacao
from saturday.bancos.granatech import status as ordem
from saturday.bancos.granatech.cliente import ClienteGranatech, ErroGranatech, ErroIncerto
from saturday.dados import repositorios
from saturday.dados.modelos import (
    Auditoria,
    ConsultaGranatech,
    HomologacaoGranatech,
    Integracao,
    PropostaGranatech,
    UsuarioPainel,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import tentar_trava
from saturday.jobs.granatech import aplicar_status_da_consulta
from saturday.painel import acoes
from saturday.painel.auditoria import auditar
from saturday.privacidade import MASCARAS
from saturday.settings import TZ_OPERACAO, Settings
from saturday.web.dependencies import (
    UsuarioLogado,
    exigir_csrf,
    gestor_com_csrf,
    gestor_logado,
    get_agent_service,
    get_fabrica,
    get_settings,
    usuario_logado,
)

router = APIRouter(prefix="/admin/granatech", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
ComCsrf = Annotated[UsuarioLogado, Depends(exigir_csrf)]
Gestor = Annotated[UsuarioLogado, Depends(gestor_logado)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]
Servico = Annotated[AgentService, Depends(get_agent_service)]

LIMITE = 200
SEM_CONVERSA = "sem conversa ligada"


class Cancelamento(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)


class Conta(BaseModel):
    banco_codigo: str = Field(pattern=r"^\d{1,5}$")
    agencia: str = Field(pattern=r"^\d{1,6}$")
    digito_agencia: str = Field(default="", pattern=r"^[0-9Xx]?$")
    numero_conta: str = Field(pattern=r"^\d{1,20}$")
    digito_conta: str = Field(pattern=r"^[0-9Xx]$")
    tipo_conta: Literal["conta_corrente", "conta_poupanca"]


# ------------------------------------------------------------------ apoio


def _cliente(request: Request) -> ClienteGranatech:
    cliente = get_agent_service(request).context.granatech
    if cliente is None:
        raise HTTPException(status_code=503, detail="Granatech desligada")
    return cliente


def _cpf(cpf: str | None) -> str | None:
    if cpf is None:
        return None
    digitos = "".join(c for c in cpf if c.isdigit())
    if len(digitos) != 11:
        raise HTTPException(status_code=422, detail="CPF precisa de 11 dígitos")
    return digitos


def _periodo(desde: date | None, ate: date | None) -> tuple[datetime | None, datetime | None]:
    tz = ZoneInfo(TZ_OPERACAO)
    inicio = datetime.combine(desde, time.min, tz) if desde else None
    fim = datetime.combine(ate, time.max, tz) if ate else None
    return inicio, fim


def _iso(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor else None


def _jornada(service: AgentService, conversation_id: str | None) -> Jornada | None:
    return service.jornada(conversation_id) if conversation_id else None


def _falha(exc: ErroGranatech) -> HTTPException:
    if isinstance(exc, ErroIncerto):
        return HTTPException(
            status_code=502, detail="resultado incerto na Granatech: confira antes de repetir"
        )
    return HTTPException(status_code=502, detail="a Granatech não respondeu como esperado")


def _auditar(
    fabrica: sessionmaker[Session],
    usuario: UsuarioLogado,
    acao: str,
    alvo: str,
    detalhe: dict[str, Any] | None = None,
) -> None:
    # Commit antes de chamar o banco: ação sem rastro não acontece.
    with abrir_sessao(fabrica) as sessao:
        auditar(sessao, usuario.id, acao, alvo, detalhe)


def _auditada[T](
    fabrica: sessionmaker[Session],
    usuario: UsuarioLogado,
    acao: str,
    alvo: str,
    chamada: Callable[[], T],
    detalhe: dict[str, Any] | None = None,
) -> T:
    """Audita e só então chama a Granatech; a falha dela vira 502."""

    _auditar(fabrica, usuario, acao, alvo, detalhe)
    try:
        return chamada()
    except ErroGranatech as exc:
        raise _falha(exc) from exc


def _avisar(fabrica: sessionmaker[Session], **ids: Any) -> None:
    with abrir_sessao(fabrica) as sessao:
        repositorios.notificar(sessao, "granatech", **ids)


# ------------------------------------------------------------------ ações possíveis


def acoes_da_consulta(linha: ConsultaGranatech) -> dict[str, str | None]:
    """Cada ação com ``None`` (pode) ou o motivo de não poder."""

    detalhe: str | None = None
    if linha.conversa_id is None:
        detalhe = SEM_CONVERSA
    elif linha.detalhe is not None:
        detalhe = "o detalhe já foi gravado"
    elif ordem.final(ordem.CONSULTA, linha.status) and linha.status != "SUCCESS":
        detalhe = "consulta encerrada sem margens"
    return {"atualizar_detalhe": detalhe}


def acoes_da_proposta(linha: PropostaGranatech, conta_ativa: bool) -> dict[str, str | None]:
    """Cada ação com ``None`` (pode) ou o motivo de não poder."""

    sem_conversa = SEM_CONVERSA if linha.conversa_id is None else None
    encerrada = "proposta encerrada" if ordem.final(ordem.PROPOSTA, linha.status) else None
    sem_id = "proposta ainda sem id na Granatech" if not linha.id_externo else None
    acao = ordem.acao_da_proposta(linha.status, linha.tipo_notificacao)
    return {
        "reconciliar": sem_conversa
        or (None if linha.estado_envio == "incerta" else "só proposta com envio incerto"),
        "reenviar_link": sem_conversa
        or sem_id
        or (None if acao in ("formalizar", "refazer") else "proposta fora da formalização"),
        "cancelar": sem_conversa or sem_id or encerrada,
        "corrigir_conta": ("correção de conta desligada" if not conta_ativa else None)
        or sem_conversa
        or sem_id
        # A Granatech só aceita a conta nova com a proposta parada na revisão.
        or (None if linha.status == "PENDING_USER_REVIEW" else "proposta fora da revisão de dados"),
    }


def _exigir(motivos: dict[str, str | None], acao: str) -> None:
    motivo = motivos[acao]
    if motivo is not None:
        raise HTTPException(status_code=409, detail=motivo)


# ------------------------------------------------------------------ leitura


@router.get("/consultas")
def listar_consultas(
    _usuario: Logado,
    fabrica: Fabrica,
    status: str | None = None,
    desde: date | None = None,
    ate: date | None = None,
    cpf: str | None = None,
) -> list[dict[str, Any]]:
    inicio, fim = _periodo(desde, ate)
    # As de membro testador, do simulador (decisão 0020), ficam fora da aba Bancos.
    filtro = (
        select(ConsultaGranatech)
        .where(ConsultaGranatech.teste.is_(False))
        .order_by(ConsultaGranatech.criada_em.desc())
        .limit(LIMITE)
    )
    if status:
        filtro = filtro.where(ConsultaGranatech.status == status)
    if inicio:
        filtro = filtro.where(ConsultaGranatech.criada_em >= inicio)
    if fim:
        filtro = filtro.where(ConsultaGranatech.criada_em <= fim)
    if (digitos := _cpf(cpf)) is not None:
        filtro = filtro.where(ConsultaGranatech.cpf == digitos)
    with abrir_sessao(fabrica) as sessao:
        return [_linha_consulta(c) for c in sessao.scalars(filtro).all()]


def _linha_consulta(c: ConsultaGranatech) -> dict[str, Any]:
    return {
        "id": c.id,
        "id_externo": c.id_externo,
        "cpf": MASCARAS["cpf"](c.cpf),
        "status": c.status,
        "conversa_id": str(c.conversa_id) if c.conversa_id else None,
        "tem_detalhe": c.detalhe is not None,
        "criada_em": _iso(c.criada_em),
        "atualizada_em": _iso(c.atualizada_em),
    }


@router.get("/propostas")
def listar_propostas(
    _usuario: Logado,
    fabrica: Fabrica,
    status: str | None = None,
    desde: date | None = None,
    ate: date | None = None,
    cpf: str | None = None,
) -> list[dict[str, Any]]:
    inicio, fim = _periodo(desde, ate)
    filtro = (
        select(PropostaGranatech, ConsultaGranatech.cpf)
        .join(ConsultaGranatech, ConsultaGranatech.id == PropostaGranatech.consulta_id)
        .where(PropostaGranatech.teste.is_(False))
        .order_by(PropostaGranatech.intencao_em.desc())
        .limit(LIMITE)
    )
    if status:
        filtro = filtro.where(PropostaGranatech.status == status)
    if inicio:
        filtro = filtro.where(PropostaGranatech.intencao_em >= inicio)
    if fim:
        filtro = filtro.where(PropostaGranatech.intencao_em <= fim)
    if (digitos := _cpf(cpf)) is not None:
        filtro = filtro.where(ConsultaGranatech.cpf == digitos)
    with abrir_sessao(fabrica) as sessao:
        return [_linha_proposta(p, c) for p, c in sessao.execute(filtro).all()]


def _linha_proposta(p: PropostaGranatech, cpf: str) -> dict[str, Any]:
    return {
        "id": p.id,
        "id_externo": p.id_externo,
        "consulta_id": p.consulta_id,
        "cpf": MASCARAS["cpf"](cpf),
        "estado_envio": p.estado_envio,
        "status": p.status,
        "tipo_notificacao": p.tipo_notificacao,
        "valor_parcela": str(p.valor_parcela),
        "numero_parcelas": p.numero_parcelas,
        "conversa_id": str(p.conversa_id) if p.conversa_id else None,
        "intencao_em": _iso(p.intencao_em),
        "atualizada_em": _iso(p.atualizada_em),
    }


@router.get("/consultas/{consulta_id}")
def ver_consulta(
    consulta_id: int, _usuario: Logado, fabrica: Fabrica, service: Servico
) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(ConsultaGranatech, consulta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="consulta não encontrada")
        conversation_id = repositorios.conversation_id_de(sessao, linha.conversa_id)
        propostas = sessao.scalars(
            select(PropostaGranatech.id).where(PropostaGranatech.consulta_id == linha.id)
        ).all()
        detalhe = linha.detalhe or {}
        jornada = _jornada(service, conversation_id)
        # Da pessoa só idade e sexo: nome, mãe e endereço ficam fora do painel.
        pessoa = detalhe.get("pessoa_natural") or {}
        return {
            **_linha_consulta(linha),
            "historico": linha.historico,
            "vinculos": detalhe.get("margens") or [],
            "idade": pessoa.get("age"),
            "sexo": pessoa.get("gender"),
            "propostas": list(propostas),
            "etapa": jornada.etapa_clt if jornada else None,
            "acoes": acoes_da_consulta(linha),
        }


@router.get("/propostas/{proposta_id}")
def ver_proposta(
    proposta_id: int, request: Request, _usuario: Logado, fabrica: Fabrica, service: Servico
) -> dict[str, Any]:
    conta_ativa = get_settings(request).granatech_dados_bancarios_ativo
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(PropostaGranatech, proposta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="proposta não encontrada")
        cpf = sessao.scalar(
            select(ConsultaGranatech.cpf).where(ConsultaGranatech.id == linha.consulta_id)
        )
        conversation_id = repositorios.conversation_id_de(sessao, linha.conversa_id)
        jornada = _jornada(service, conversation_id)
        return {
            **_linha_proposta(linha, cpf or ""),
            "historico": linha.historico,
            "etapa": jornada.etapa_clt if jornada else None,
            # Propostas antigas não guardam as condições: só a oferta do checkpoint,
            # enquanto a conversa ainda aponta para esta proposta.
            "oferta": linha.condicoes
            or (jornada.oferta if jornada and jornada.proposta == linha.id_externo else None),
            "conta_ativa": conta_ativa,
            "acoes": acoes_da_proposta(linha, conta_ativa),
        }


@router.post("/consultas/{consulta_id}/revelar")
def revelar_cpf(consulta_id: int, usuario: ComCsrf, fabrica: Fabrica) -> dict[str, str]:
    with abrir_sessao(fabrica) as sessao:
        cpf = sessao.scalar(
            select(ConsultaGranatech.cpf).where(ConsultaGranatech.id == consulta_id)
        )
        if cpf is None:
            raise HTTPException(status_code=404, detail="consulta não encontrada")
        # Na mesma transação: sem a linha de auditoria, o dado não sai.
        auditar(sessao, usuario.id, "revelar:cpf", f"consulta:{consulta_id}")
    return {"campo": "cpf", "valor": cpf}


@router.get("/bancos")
def bancos(request: Request, _usuario: Logado) -> list[dict[str, str]]:
    try:
        lista = _cliente(request).bancos_em_cache()
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    return [{"codigo": str(b.get("codigo")), "nome": str(b.get("nome"))} for b in lista]


# ------------------------------------------------------------------ ações do gestor

# Depois de um reenvio, o link da mesma proposta espera este prazo (decisão 0025).
PRAZO_REENVIO = timedelta(minutes=1)


def _travar(fabrica: sessionmaker[Session], tipo: str, item_id: int) -> Iterator[None]:
    """Uma ação por vez em cada item: a segunda é recusada, não espera.

    A trava vive nesta sessão, que fica aberta até a resposta sair. Não é a
    da conversa: o turno de sistema pega aquela em outra sessão, e a ação
    ficaria esperando por si mesma.
    """

    with abrir_sessao(fabrica) as sessao:
        if not tentar_trava(sessao, f"granatech:{tipo}:{item_id}"):
            raise HTTPException(status_code=409, detail=f"outra ação em andamento nesta {tipo}")
        yield


# O gestor entra na assinatura para a trava só ser tentada por quem pode agir.
def _proposta_travada(proposta_id: int, fabrica: Fabrica, _usuario: GestorCsrf) -> Iterator[None]:
    yield from _travar(fabrica, "proposta", proposta_id)


def _consulta_travada(consulta_id: int, fabrica: Fabrica, _usuario: GestorCsrf) -> Iterator[None]:
    yield from _travar(fabrica, "consulta", consulta_id)


UMA_POR_PROPOSTA = [Depends(_proposta_travada)]


def _conferir_prazo_do_reenvio(fabrica: sessionmaker[Session], proposta_id: int) -> None:
    """Recusa o link reenviado há pouco. Roda sob a trava da proposta."""

    with abrir_sessao(fabrica) as sessao:
        # O SQLAlchemy tipa a diferença como data; o Postgres devolve um intervalo.
        ha = cast(
            "timedelta | None",
            sessao.scalar(
                select(func.now() - func.max(Auditoria.criada_em)).where(
                    Auditoria.acao == "granatech_reenviar_link",
                    Auditoria.alvo == f"proposta:{proposta_id}",
                )
            ),
        )
    if ha is not None and ha < PRAZO_REENVIO:
        falta = ceil((PRAZO_REENVIO - ha).total_seconds())
        raise HTTPException(
            status_code=409,
            detail=f"link reenviado há {int(ha.total_seconds())} s; tente de novo em {falta} s",
        )


def _proposta(
    fabrica: sessionmaker[Session], proposta_id: int, acao: str, conta_ativa: bool = False
) -> tuple[PropostaGranatech, str]:
    """Carrega a proposta e confere se a ação vale: 404 ou 409."""

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(PropostaGranatech, proposta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="proposta não encontrada")
        _exigir(acoes_da_proposta(linha, conta_ativa), acao)
        sessao.expunge(linha)
        return linha, repositorios.conversation_id_de(sessao, linha.conversa_id) or ""


@router.post("/propostas/{proposta_id}/reconciliar", dependencies=UMA_POR_PROPOSTA)
def reconciliar(
    proposta_id: int,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
    service: Servico,
) -> dict[str, Any]:
    """Procura a proposta incerta na listagem; achada, a jornada segue com a IA."""

    cliente = _cliente(request)
    linha, conversation_id = _proposta(fabrica, proposta_id, "reconciliar")
    achada = _auditada(
        fabrica,
        usuario,
        "granatech_reconciliar",
        f"proposta:{proposta_id}",
        lambda: cliente.reconciliar_proposta(proposta_id),
    )
    if achada is None:
        _avisar(fabrica, proposta=proposta_id)
        return {"achada": False}

    conversa_id = cast(uuid.UUID, linha.conversa_id)  # conferido em `acoes_da_proposta`
    try:
        service.devolver(conversa_id, usuario.id, gestor=True)
    except acoes.AcaoRecusada as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detalhe) from exc
    # Do aceite em diante: `criar_proposta` devolve a que achamos, sem novo POST.
    service.continuar(conversation_id, "painel:reconciliar")
    _avisar(fabrica, proposta=proposta_id)
    return {"achada": True, "id_externo": achada}


@router.post(
    "/propostas/{proposta_id}/reenviar-link", status_code=204, dependencies=UMA_POR_PROPOSTA
)
def reenviar_link(
    proposta_id: int, request: Request, usuario: GestorCsrf, fabrica: Fabrica, service: Servico
) -> Response:
    """Manda de novo o link vigente da biometria, mesmo com a conversa com humano."""

    _cliente(request)
    linha, conversation_id = _proposta(fabrica, proposta_id, "reenviar_link")
    _conferir_prazo_do_reenvio(fabrica, proposta_id)
    _auditar(fabrica, usuario, "granatech_reenviar_link", f"proposta:{proposta_id}")
    acao = ordem.acao_da_proposta(linha.status, linha.tipo_notificacao)
    service.continuar(conversation_id, f"proposta:{acao}", forcar=True)
    return Response(status_code=204)


@router.post("/propostas/{proposta_id}/cancelar", status_code=204, dependencies=UMA_POR_PROPOSTA)
def cancelar(
    proposta_id: int,
    dados: Cancelamento,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
) -> Response:
    """Pede o cancelamento; o cliente é avisado quando o webhook ``CANCELED`` chegar."""

    cliente = _cliente(request)
    linha, _ = _proposta(fabrica, proposta_id, "cancelar")
    _auditada(
        fabrica,
        usuario,
        "granatech_cancelar",
        f"proposta:{proposta_id}",
        lambda: cliente.cancelar(str(linha.id_externo), conversa_id=linha.conversa_id),
        {"motivo": dados.motivo.strip()},
    )
    return Response(status_code=204)


@router.post("/propostas/{proposta_id}/conta", status_code=204, dependencies=UMA_POR_PROPOSTA)
def corrigir_conta(
    proposta_id: int,
    dados: Conta,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
) -> Response:
    """Nova conta digitada pelo gestor; a conversa segue com quem está."""

    if not get_settings(request).granatech_dados_bancarios_ativo:
        raise HTTPException(status_code=404, detail="correção de conta desligada")
    cliente = _cliente(request)
    linha, _ = _proposta(fabrica, proposta_id, "corrigir_conta", conta_ativa=True)
    try:
        habilitados = {str(b.get("codigo")) for b in cliente.bancos_em_cache()}
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    if dados.banco_codigo not in habilitados:
        raise HTTPException(status_code=422, detail="banco fora da lista da Granatech")
    _auditada(
        fabrica,
        usuario,
        "granatech_corrigir_conta",
        f"proposta:{proposta_id}",
        lambda: cliente.corrigir_dados_bancarios(
            str(linha.id_externo), dados.model_dump(), conversa_id=linha.conversa_id
        ),
        {"banco": dados.banco_codigo, "final_conta": dados.numero_conta[-2:]},
    )
    return Response(status_code=204)


@router.post(
    "/consultas/{consulta_id}/atualizar-detalhe", dependencies=[Depends(_consulta_travada)]
)
def atualizar_detalhe(
    consulta_id: int, request: Request, usuario: GestorCsrf, fabrica: Fabrica, service: Servico
) -> dict[str, bool]:
    """Relê o detalhe de uma consulta parada; com margens, ela está pronta."""

    cliente = _cliente(request)
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(ConsultaGranatech, consulta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="consulta não encontrada")
        _exigir(acoes_da_consulta(linha), "atualizar_detalhe")
        id_externo = linha.id_externo
        conversation_id = repositorios.conversation_id_de(sessao, linha.conversa_id) or ""
    detalhe = _auditada(
        fabrica,
        usuario,
        "granatech_atualizar_detalhe",
        f"consulta:{consulta_id}",
        lambda: cliente.gravar_detalhe(id_externo),
    )
    if detalhe is None:
        return {"pronto": False}

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(ConsultaGranatech).where(ConsultaGranatech.id == consulta_id).with_for_update()
        ).one()
        # Detalhe com margens é consulta pronta (contrato); o webhook pode não ter vindo.
        aplicar_status_da_consulta(sessao, linha, "SUCCESS", origem="painel")
    # Só avança se a conversa ainda está em `consultando`; com humano vira alerta.
    service.continuar(conversation_id, "consulta_pronta")
    return {"pronto": True}


# ------------------------------------------------------------ homologação (decisão 0014)
# O painel e a integração (decisão 0035, fase 4) usam as mesmas funções abaixo.


class PedidoRodada(BaseModel):
    fase: Literal[1, 2]


def homologacao_disponivel(request: Request) -> Settings:
    settings = get_settings(request)
    if not homologacao.disponivel(settings):
        raise HTTPException(status_code=404, detail="homologação indisponível neste ambiente")
    return settings


def _linha_rodada(r: HomologacaoGranatech, nome: str | None) -> dict[str, Any]:
    return {
        "id": r.id,
        "fase": r.fase,
        "situacao": r.situacao,
        "pedido_por": nome,
        "criado_em": _iso(r.criado_em),
        "iniciado_em": _iso(r.iniciado_em),
        "terminado_em": _iso(r.terminado_em),
        "erro": r.erro,
        # Um booleano por item já anotado, na ordem do roteiro da fase.
        "progresso": {
            "total": len(homologacao.ITENS_POR_FASE[r.fase]),
            "ok": [bool(i["ok"]) for i in r.itens],
        },
    }


def _com_quem_pediu() -> Any:
    # Quem pediu: a pessoa do painel ou, sem ela, a integração.
    return (
        select(HomologacaoGranatech, func.coalesce(UsuarioPainel.nome, Integracao.nome))
        .outerjoin(UsuarioPainel, UsuarioPainel.id == HomologacaoGranatech.pedido_por)
        .outerjoin(Integracao, Integracao.id == HomologacaoGranatech.integracao_id)
    )


def _rodada(sessao: Session, rodada_id: int) -> tuple[HomologacaoGranatech, str | None]:
    linha = sessao.execute(_com_quem_pediu().where(HomologacaoGranatech.id == rodada_id)).first()
    if linha is None:
        raise HTTPException(status_code=404, detail="rodada não encontrada")
    return linha[0], linha[1]


def listar_rodadas_json(settings: Settings, fabrica: sessionmaker[Session]) -> dict[str, Any]:
    dominio = settings.dominio_publico
    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.execute(
            _com_quem_pediu().order_by(HomologacaoGranatech.id.desc()).limit(LIMITE)
        ).all()
        rodadas = [_linha_rodada(r, nome) for r, nome in linhas]
    return {
        "webhook_esperado": f"https://{dominio}/webhooks/granatech" if dominio else None,
        "base_granatech": settings.granatech_base_url,
        "consultas_por_fase": homologacao.CONSULTAS_POR_FASE,
        "rodadas": rodadas,
    }


def pedir_rodada_json(
    fabrica: sessionmaker[Session],
    fase: int,
    *,
    usuario_id: uuid.UUID | None,
    integracao_id: uuid.UUID | None,
    nome: str,
) -> dict[str, Any]:
    try:
        with abrir_sessao(fabrica) as sessao:
            rodada = HomologacaoGranatech(
                fase=fase, pedido_por=usuario_id, integracao_id=integracao_id
            )
            sessao.add(rodada)
            sessao.flush()
            detalhe: dict[str, Any] = {"fase": fase}
            if integracao_id is not None:
                detalhe |= {"origem": "integracao", "integracao": str(integracao_id)}
            auditar(sessao, usuario_id, "granatech:homologacao", f"rodada:{rodada.id}", detalhe)
            repositorios.notificar(sessao, "homologacao", rodada=rodada.id)
            return _linha_rodada(rodada, nome)
    except IntegrityError:
        # Índice único: já existe uma rodada pendente ou em andamento.
        raise HTTPException(status_code=409, detail="já há uma rodada em andamento") from None


def ver_rodada_json(fabrica: sessionmaker[Session], rodada_id: int) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        rodada, nome = _rodada(sessao, rodada_id)
        return {
            **_linha_rodada(rodada, nome),
            "itens_previstos": homologacao.ITENS_POR_FASE[rodada.fase],
            "itens": rodada.itens,
            "passos": rodada.passos,
        }


def zip_da_rodada(settings: Settings, fabrica: sessionmaker[Session], rodada_id: int) -> Response:
    with abrir_sessao(fabrica) as sessao:
        rodada, _nome = _rodada(sessao, rodada_id)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
            for passo in rodada.passos:
                conteudo = {k: v for k, v in passo.items() if k != "arquivo"}
                arquivo.writestr(
                    passo["arquivo"], json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n"
                )
            arquivo.writestr(
                "RELATORIO.md",
                homologacao.relatorio(
                    rodada.itens,
                    settings.granatech_base_url,
                    rodada.terminado_em or rodada.criado_em,
                    rodada.erro,
                ),
            )
        nome = f"granatech-fase{rodada.fase}-rodada{rodada.id}.zip"
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/homologacao")
def listar_rodadas(request: Request, _usuario: Gestor, fabrica: Fabrica) -> dict[str, Any]:
    return listar_rodadas_json(homologacao_disponivel(request), fabrica)


@router.post("/homologacao", status_code=201)
def pedir_rodada(
    pedido: PedidoRodada, request: Request, usuario: GestorCsrf, fabrica: Fabrica
) -> dict[str, Any]:
    homologacao_disponivel(request)
    return pedir_rodada_json(
        fabrica, pedido.fase, usuario_id=usuario.id, integracao_id=None, nome=usuario.nome
    )


@router.get("/homologacao/{rodada_id}")
def ver_rodada(
    rodada_id: int, request: Request, _usuario: Gestor, fabrica: Fabrica
) -> dict[str, Any]:
    homologacao_disponivel(request)
    return ver_rodada_json(fabrica, rodada_id)


@router.get("/homologacao/{rodada_id}/zip")
def baixar_rodada(rodada_id: int, request: Request, _usuario: Gestor, fabrica: Fabrica) -> Response:
    return zip_da_rodada(homologacao_disponivel(request), fabrica, rodada_id)
