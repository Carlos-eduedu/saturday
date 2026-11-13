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
from datetime import UTC, date, datetime, time
from typing import Annotated, Any, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech import homologacao
from saturday.bancos.granatech import status as ordem
from saturday.bancos.granatech.cliente import ClienteGranatech, ErroGranatech, ErroIncerto
from saturday.dados import repositorios
from saturday.dados.modelos import (
    ConsultaGranatech,
    Conversa,
    HomologacaoGranatech,
    PropostaGranatech,
    UsuarioPainel,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import acoes
from saturday.painel.auditoria import auditar
from saturday.privacidade import MASCARAS
from saturday.settings import TZ_OPERACAO, Settings
from saturday.web.dependencies import (
    UsuarioLogado,
    exigir_csrf,
    exigir_fabrica,
    gestor_com_csrf,
    gestor_logado,
    get_agent_service,
    get_settings,
    usuario_logado,
)

router = APIRouter(prefix="/admin/granatech", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
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


def _conversation_id(sessao: Session, conversa_id: uuid.UUID | None) -> str | None:
    if conversa_id is None:
        return None
    return sessao.scalar(select(Conversa.conversation_id).where(Conversa.id == conversa_id))


def _clt(service: AgentService, conversation_id: str | None) -> dict[str, Any]:
    if conversation_id is None:
        return {}
    estado = service.estado_atual(service.config(conversation_id))
    return dict(estado.get("clt") or {})


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
        or encerrada,
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
    filtro = select(ConsultaGranatech).order_by(ConsultaGranatech.criada_em.desc()).limit(LIMITE)
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
        conversation_id = _conversation_id(sessao, linha.conversa_id)
        propostas = sessao.scalars(
            select(PropostaGranatech.id).where(PropostaGranatech.consulta_id == linha.id)
        ).all()
        detalhe = linha.detalhe or {}
        # Da pessoa só idade e sexo: nome, mãe e endereço ficam fora do painel.
        pessoa = detalhe.get("pessoa_natural") or {}
        return {
            **_linha_consulta(linha),
            "historico": linha.historico,
            "vinculos": detalhe.get("margens") or [],
            "idade": pessoa.get("age"),
            "sexo": pessoa.get("gender"),
            "propostas": list(propostas),
            "etapa": _clt(service, conversation_id).get("etapa"),
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
        conversation_id = _conversation_id(sessao, linha.conversa_id)
        clt = _clt(service, conversation_id)
        return {
            **_linha_proposta(linha, cpf or ""),
            "historico": linha.historico,
            "etapa": clt.get("etapa"),
            "oferta": clt.get("oferta") if clt.get("proposta") == linha.id_externo else None,
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


def _proposta(fabrica: sessionmaker[Session], proposta_id: int) -> tuple[PropostaGranatech, str]:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(PropostaGranatech, proposta_id)
        if linha is None:
            raise HTTPException(status_code=404, detail="proposta não encontrada")
        sessao.expunge(linha)
        return linha, _conversation_id(sessao, linha.conversa_id) or ""


@router.post("/propostas/{proposta_id}/reconciliar")
def reconciliar(
    proposta_id: int,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
    service: Servico,
) -> dict[str, Any]:
    """Procura a proposta incerta na listagem; achada, a jornada segue com a IA."""

    cliente = _cliente(request)
    linha, conversation_id = _proposta(fabrica, proposta_id)
    _exigir(acoes_da_proposta(linha, False), "reconciliar")
    _auditar(fabrica, usuario, "granatech_reconciliar", f"proposta:{proposta_id}")
    try:
        achada = cliente.reconciliar_proposta(proposta_id)
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    if achada is None:
        _avisar(fabrica, proposta=proposta_id)
        return {"achada": False}

    conversa_id = cast(uuid.UUID, linha.conversa_id)  # conferido em `acoes_da_proposta`
    try:
        with acoes.conversa_travada(fabrica, conversa_id) as (sessao, conversa):
            acoes.devolver(sessao, conversa, usuario.id, gestor=True)
    except acoes.AcaoRecusada as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detalhe) from exc
    service.limpar_handoff(conversation_id)
    # Do aceite em diante: `criar_proposta` devolve a que achamos, sem novo POST.
    service.continuar(conversation_id, "painel:reconciliar")
    _avisar(fabrica, proposta=proposta_id)
    return {"achada": True, "id_externo": achada}


@router.post("/propostas/{proposta_id}/reenviar-link", status_code=204)
def reenviar_link(
    proposta_id: int, request: Request, usuario: GestorCsrf, fabrica: Fabrica, service: Servico
) -> Response:
    """Manda de novo o link vigente da biometria, mesmo com a conversa com humano."""

    _cliente(request)
    linha, conversation_id = _proposta(fabrica, proposta_id)
    _exigir(acoes_da_proposta(linha, False), "reenviar_link")
    _auditar(fabrica, usuario, "granatech_reenviar_link", f"proposta:{proposta_id}")
    acao = ordem.acao_da_proposta(linha.status, linha.tipo_notificacao)
    service.continuar(conversation_id, f"proposta:{acao}", forcar=True)
    return Response(status_code=204)


@router.post("/propostas/{proposta_id}/cancelar", status_code=204)
def cancelar(
    proposta_id: int,
    dados: Cancelamento,
    request: Request,
    usuario: GestorCsrf,
    fabrica: Fabrica,
) -> Response:
    """Pede o cancelamento; o cliente é avisado quando o webhook ``CANCELED`` chegar."""

    cliente = _cliente(request)
    linha, _ = _proposta(fabrica, proposta_id)
    _exigir(acoes_da_proposta(linha, False), "cancelar")
    _auditar(
        fabrica,
        usuario,
        "granatech_cancelar",
        f"proposta:{proposta_id}",
        {"motivo": dados.motivo.strip()},
    )
    try:
        cliente.cancelar(str(linha.id_externo), conversa_id=linha.conversa_id)
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    return Response(status_code=204)


@router.post("/propostas/{proposta_id}/conta", status_code=204)
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
    linha, _ = _proposta(fabrica, proposta_id)
    _exigir(acoes_da_proposta(linha, True), "corrigir_conta")
    try:
        habilitados = {str(b.get("codigo")) for b in cliente.bancos_em_cache()}
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    if dados.banco_codigo not in habilitados:
        raise HTTPException(status_code=422, detail="banco fora da lista da Granatech")
    _auditar(
        fabrica,
        usuario,
        "granatech_corrigir_conta",
        f"proposta:{proposta_id}",
        {"banco": dados.banco_codigo, "final_conta": dados.numero_conta[-2:]},
    )
    try:
        cliente.corrigir_dados_bancarios(
            str(linha.id_externo), dados.model_dump(), conversa_id=linha.conversa_id
        )
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    return Response(status_code=204)


@router.post("/consultas/{consulta_id}/atualizar-detalhe")
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
        conversation_id = _conversation_id(sessao, linha.conversa_id) or ""
    _auditar(fabrica, usuario, "granatech_atualizar_detalhe", f"consulta:{consulta_id}")
    try:
        detalhe = cliente.gravar_detalhe(id_externo)
    except ErroGranatech as exc:
        raise _falha(exc) from exc
    if detalhe is None:
        return {"pronto": False}

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(ConsultaGranatech).where(ConsultaGranatech.id == consulta_id).with_for_update()
        ).one()
        # Detalhe com margens é consulta pronta (contrato); o webhook pode não ter vindo.
        if ordem.aceita_consulta(linha.status, "SUCCESS"):
            linha.status = "SUCCESS"
        linha.historico = [
            *linha.historico,
            {"status": "SUCCESS", "origem": "painel", "recebido_em": datetime.now(UTC).isoformat()},
        ]
        repositorios.notificar(sessao, "granatech", consulta=consulta_id)
    # Só avança se a conversa ainda está em `consultando`; com humano vira alerta.
    service.continuar(conversation_id, "consulta_pronta")
    return {"pronto": True}


# ------------------------------------------------------------ homologação (decisão 0014)


class PedidoRodada(BaseModel):
    fase: Literal[1, 2]


def _homologacao_disponivel(request: Request) -> Settings:
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


def _rodada(sessao: Session, rodada_id: int) -> tuple[HomologacaoGranatech, str | None]:
    linha = sessao.execute(
        select(HomologacaoGranatech, UsuarioPainel.nome)
        .outerjoin(UsuarioPainel, UsuarioPainel.id == HomologacaoGranatech.pedido_por)
        .where(HomologacaoGranatech.id == rodada_id)
    ).first()
    if linha is None:
        raise HTTPException(status_code=404, detail="rodada não encontrada")
    return linha[0], linha[1]


@router.get("/homologacao")
def listar_rodadas(request: Request, _usuario: Gestor, fabrica: Fabrica) -> dict[str, Any]:
    settings = _homologacao_disponivel(request)
    dominio = settings.dominio_publico
    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.execute(
            select(HomologacaoGranatech, UsuarioPainel.nome)
            .outerjoin(UsuarioPainel, UsuarioPainel.id == HomologacaoGranatech.pedido_por)
            .order_by(HomologacaoGranatech.id.desc())
            .limit(LIMITE)
        ).all()
        rodadas = [_linha_rodada(r, nome) for r, nome in linhas]
    return {
        "webhook_esperado": f"https://{dominio}/webhooks/granatech" if dominio else None,
        "base_granatech": settings.granatech_base_url,
        "consultas_por_fase": homologacao.CONSULTAS_POR_FASE,
        "rodadas": rodadas,
    }


@router.post("/homologacao", status_code=201)
def pedir_rodada(
    pedido: PedidoRodada, request: Request, usuario: GestorCsrf, fabrica: Fabrica
) -> dict[str, Any]:
    _homologacao_disponivel(request)
    try:
        with abrir_sessao(fabrica) as sessao:
            rodada = HomologacaoGranatech(fase=pedido.fase, pedido_por=usuario.id)
            sessao.add(rodada)
            sessao.flush()
            auditar(
                sessao,
                usuario.id,
                "granatech:homologacao",
                f"rodada:{rodada.id}",
                {"fase": pedido.fase},
            )
            repositorios.notificar(sessao, "homologacao", rodada=rodada.id)
            return _linha_rodada(rodada, usuario.nome)
    except IntegrityError:
        # Índice único: já existe uma rodada pendente ou em andamento.
        raise HTTPException(status_code=409, detail="já há uma rodada em andamento") from None


@router.get("/homologacao/{rodada_id}")
def ver_rodada(
    rodada_id: int, request: Request, _usuario: Gestor, fabrica: Fabrica
) -> dict[str, Any]:
    _homologacao_disponivel(request)
    with abrir_sessao(fabrica) as sessao:
        rodada, nome = _rodada(sessao, rodada_id)
        return {
            **_linha_rodada(rodada, nome),
            "itens_previstos": homologacao.ITENS_POR_FASE[rodada.fase],
            "itens": rodada.itens,
            "passos": rodada.passos,
        }


@router.get("/homologacao/{rodada_id}/zip")
def baixar_rodada(rodada_id: int, request: Request, _usuario: Gestor, fabrica: Fabrica) -> Response:
    settings = _homologacao_disponivel(request)
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
