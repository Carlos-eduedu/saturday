"""Proxy da Granatech para o APP MEX (decisão 0035), fase 3: escrita.

As rotas repetem as da Granatech, como na leitura, mas aqui o Saturday confere
antes de repassar: a cota (reaproveitamento por CPF, teto diário e mensal), o
teto de R$ 6.999 (pelo que a Granatech calculou na simulação repassada, nunca
pelo que o APP MEX manda), a proposta sem retry (intenção gravada antes,
reconciliação pela listagem) e o dono do item. Consulta e proposta abertas
aqui ficam com a integração dona, que recebe o aviso de status (fase 2).

Triagem e consentimento são do APP MEX (decisão 0036).
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import (
    CONSIGNADO,
    ClienteGranatech,
    ConsultaAberta,
    ErroGranatech,
    ErroIncerto,
)
from saturday.bancos.granatech.normalizacao import normalizar_simulacao
from saturday.bancos.granatech.numeros import decimal_ou_none
from saturday.dados.cota import CotaEsgotada
from saturday.dados.modelos import ConsultaGranatech, PropostaGranatech, SimulacaoIntegracao
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import mascarar_cpfs
from saturday.web.api.integracao_granatech import GRANATECH, Granatech, Id
from saturday.web.dependencies import IntegracaoLogada, get_fabrica, get_settings, integracao

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integracao", tags=["integracao"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Operacoes = Annotated[IntegracaoLogada, Depends(integracao("operacoes"))]
Acoes = Annotated[IntegracaoLogada, Depends(integracao("acoes"))]
Corpo = Annotated[dict[str, Any], Body()]

# Simulação vale para a proposta por um dia: a Granatech recalcula condições.
VALIDADE_SIMULACAO = timedelta(hours=24)
DE_OUTRO_DONO = "item de outra integração ou de uma conversa do agente"


def _resposta(status: int, corpo: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content=mascarar_cpfs(corpo))


def _repassar(
    cliente: ClienteGranatech,
    metodo: str,
    rota_modelo: str,
    caminho: str,
    *,
    params: httpx.QueryParams | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    try:
        return cliente.repassar(
            metodo, f"{CONSIGNADO}{rota_modelo}", f"{CONSIGNADO}{caminho}", params, json
        )
    except ErroIncerto as exc:
        # Pode ter sido feito: quem chamou confere antes de repetir (regra 4).
        raise HTTPException(
            status_code=502, detail="resultado incerto na Granatech: confira antes de repetir"
        ) from exc
    except ErroGranatech as exc:
        raise HTTPException(status_code=502, detail="Granatech indisponível") from exc


def _dono(item_integracao: Any, item_conversa: Any, quem: IntegracaoLogada) -> None:
    """Só a integração que abriu escreve no item (decisão 0013: a etapa mentiria)."""

    if item_conversa is not None or item_integracao != quem.id:
        raise HTTPException(status_code=409, detail=DE_OUTRO_DONO)


def _consulta_da_integracao(
    fabrica: sessionmaker[Session], id_consulta: str, quem: IntegracaoLogada
) -> ConsultaGranatech:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(ConsultaGranatech).where(
                ConsultaGranatech.id_externo == id_consulta,
                ConsultaGranatech.teste.is_(False),
            )
        ).first()
        if linha is None:
            raise HTTPException(status_code=404, detail="consulta não encontrada")
        _dono(linha.integracao_id, linha.conversa_id, quem)
        sessao.expunge(linha)
        return linha


def _proposta_da_integracao(
    fabrica: sessionmaker[Session], id_proposta: str, quem: IntegracaoLogada
) -> PropostaGranatech:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(PropostaGranatech).where(
                PropostaGranatech.id_externo == id_proposta,
                PropostaGranatech.teste.is_(False),
            )
        ).first()
        if linha is None:
            raise HTTPException(status_code=404, detail="proposta não encontrada")
        _dono(linha.integracao_id, linha.conversa_id, quem)
        sessao.expunge(linha)
        return linha


# ------------------------------------------------------------------ consulta


def _digitos(valor: str | None, tamanho: int, campo: str) -> str:
    digitos = re.sub(r"\D", "", valor or "")
    if len(digitos) != tamanho:
        raise HTTPException(status_code=422, detail=f"{campo} precisa de {tamanho} dígitos")
    return digitos


def conferir_reaproveitada(aberta: ConsultaAberta, quem: IntegracaoLogada) -> None:
    """Consulta reaproveitada de outro dono não volta ao APP MEX.

    TODO(decisão): CPF em conversa com o agente — ver a pergunta no Inbox.
    """

    if aberta.reaproveitada and (aberta.conversa_id is not None or aberta.integracao_id != quem.id):
        raise HTTPException(status_code=409, detail="CPF em atendimento por outro canal")


@router.get(f"{GRANATECH}/consulta-saldo")
def abrir_consulta(
    quem: Operacoes,
    cliente: Granatech,
    cpf: str | None = None,
    nome: str | None = None,
    telefone: str | None = None,
) -> JSONResponse:
    """Abre a consulta (gasta cota) ou devolve a recente do mesmo CPF (não gasta)."""

    cpf = _digitos(cpf, 11, "cpf")
    telefone = _digitos(telefone, 11, "telefone")
    nome = (nome or "").strip()
    if not nome:
        raise HTTPException(status_code=422, detail="nome é obrigatório")
    try:
        aberta = cliente.abrir_consulta(cpf, nome, telefone, integracao_id=quem.id)
    except CotaEsgotada as exc:
        raise HTTPException(status_code=429, detail="cota da Granatech esgotada") from exc
    except ErroGranatech as exc:
        if exc.status is not None and 400 <= exc.status < 500 and exc.status not in (401, 403):
            return _resposta(exc.status, exc.corpo)
        raise HTTPException(status_code=502, detail="Granatech indisponível") from exc
    conferir_reaproveitada(aberta, quem)
    return _resposta(
        200,
        {
            "id": aberta.id_externo,
            "status": aberta.status,
            "link_termo_consentimento": aberta.link_termo,
            "reaproveitada": aberta.reaproveitada,
        },
    )


@router.post(f"{GRANATECH}/termo-consentimento")
def assinar_termo(
    corpo: Corpo, quem: Operacoes, cliente: Granatech, fabrica: Fabrica
) -> JSONResponse:
    _consulta_da_integracao(fabrica, str(corpo.get("id_consulta") or ""), quem)
    status, resposta = _repassar(
        cliente, "POST", "/termo-consentimento", "/termo-consentimento", json=corpo
    )
    return _resposta(status, resposta)


# ------------------------------------------------------------------ simulação


def _blocos(dados: Any) -> list[Any]:
    """Cada resultado que veio (com e sem seguro), já lido."""

    if not isinstance(dados, dict):
        return []
    blocos = []
    for chave in ("resultado_da_simulacao_com_seguro", "resultado_da_simulacao_sem_seguro"):
        bloco = dados.get(chave)
        if isinstance(bloco, dict) and bloco:
            blocos.append(normalizar_simulacao({chave: bloco}))
    return blocos


@router.get(f"{GRANATECH}/simulacao/{{id_produto}}")
def simular(
    id_produto: Id,
    request: Request,
    quem: Operacoes,
    cliente: Granatech,
    fabrica: Fabrica,
) -> JSONResponse:
    """Repassa a simulação; acima do teto, não apresenta (regra 6)."""

    params = httpx.QueryParams(request.url.query)
    status, dados = _repassar(
        cliente, "GET", "/simulacao/{id_produto}", f"/simulacao/{id_produto}", params=params
    )
    if status != 200:
        return _resposta(status, dados)
    try:
        blocos = _blocos(dados)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=502, detail="simulação em formato inesperado") from exc
    if not blocos:
        raise HTTPException(status_code=502, detail="simulação sem resultado")
    teto = cliente.teto
    if any(b.liberado > teto for b in blocos):
        raise HTTPException(
            status_code=422,
            detail=f"liberado acima do teto de R$ {teto}: reduza a parcela ou o prazo",
        )
    with abrir_sessao(fabrica) as sessao:
        for b in blocos:
            sessao.add(
                SimulacaoIntegracao(
                    integracao_id=quem.id,
                    id_produto=id_produto,
                    id_margem=str(params.get("id_margem") or ""),
                    numero_parcelas=b.numero_parcelas,
                    valor_parcela=b.valor_parcela,
                    liberado=b.liberado,
                )
            )
    return _resposta(200, dados)


# ------------------------------------------------------------------ proposta


def conferir_simulada(
    sessao: Session, quem: IntegracaoLogada, corpo: dict[str, Any], teto: Decimal
) -> None:
    """A proposta tem de repetir uma simulação repassada a esta integração."""

    financeiro = (corpo.get("informacoesFinanceira") or [{}])[0]
    if not isinstance(financeiro, dict):
        raise HTTPException(status_code=422, detail="informacoesFinanceira inválido")
    liberado = decimal_ou_none(financeiro.get("valor_solicitado"))
    parcela = decimal_ou_none(financeiro.get("valor_parcela"))
    prazo = financeiro.get("numero_parcelas")
    if liberado is None or parcela is None or not isinstance(prazo, int):
        raise HTTPException(
            status_code=422,
            detail="informacoesFinanceira sem valor_solicitado, valor_parcela ou numero_parcelas",
        )
    if liberado > teto:
        raise HTTPException(status_code=422, detail=f"liberado acima do teto de R$ {teto}")
    conhecida = sessao.scalar(
        select(SimulacaoIntegracao.id).where(
            SimulacaoIntegracao.integracao_id == quem.id,
            SimulacaoIntegracao.id_produto == str(corpo.get("id_produto") or ""),
            SimulacaoIntegracao.id_margem == str(corpo.get("id_margem") or ""),
            SimulacaoIntegracao.numero_parcelas == prazo,
            SimulacaoIntegracao.valor_parcela == parcela,
            SimulacaoIntegracao.liberado == liberado,
            SimulacaoIntegracao.criada_em >= func.now() - VALIDADE_SIMULACAO,
        )
    )
    if conhecida is None:
        raise HTTPException(
            status_code=422,
            detail="sem simulação igual nas últimas 24 h: simule pelo Saturday antes",
        )


@router.post(f"{GRANATECH}/propostas")
def criar_proposta(
    corpo: Corpo,
    request: Request,
    quem: Operacoes,
    cliente: Granatech,
    fabrica: Fabrica,
) -> JSONResponse:
    """Cria uma vez; repetir a mesma consulta devolve a mesma proposta, sem novo POST."""

    if not get_settings(request).granatech_proposta_ativa:
        raise HTTPException(status_code=503, detail="criação de proposta desligada")
    id_consulta = str(corpo.get("id_consulta") or "")
    consulta = _consulta_da_integracao(fabrica, id_consulta, quem)
    with abrir_sessao(fabrica) as sessao:
        conferir_simulada(sessao, quem, corpo, cliente.teto)
        ja_criada = sessao.scalar(
            select(PropostaGranatech.id_externo).where(
                PropostaGranatech.consulta_id == consulta.id,
                PropostaGranatech.estado_envio == "criada",
            )
        )
    try:
        id_externo = cliente.criar_proposta(
            consulta_id=consulta.id, corpo=corpo, integracao_id=quem.id
        )
    except ErroIncerto:
        # Sem POST de novo: a listagem é quem diz (regra 4).
        return _resposta(
            202,
            {
                "situacao": "incerta",
                "id_consulta": id_consulta,
                "detalhe": "a Granatech pode ter criado; consulte propostas/lista antes de repetir",
            },
        )
    except ErroGranatech as exc:
        if exc.status is not None and 400 <= exc.status < 500 and exc.status not in (401, 403):
            return _resposta(exc.status, exc.corpo)
        raise HTTPException(status_code=502, detail="Granatech indisponível") from exc
    return _resposta(200, {"id": id_externo, "reaproveitada": ja_criada == id_externo})


@router.post(f"{GRANATECH}/propostas/{{id_proposta}}/dados-tomador")
def dados_tomador(
    id_proposta: Id, corpo: Corpo, quem: Operacoes, cliente: Granatech, fabrica: Fabrica
) -> JSONResponse:
    _proposta_da_integracao(fabrica, id_proposta, quem)
    status, resposta = _repassar(
        cliente,
        "POST",
        "/propostas/{id}/dados-tomador",
        f"/propostas/{id_proposta}/dados-tomador",
        json=corpo,
    )
    return _resposta(status, resposta)


@router.post(f"{GRANATECH}/propostas/{{id_proposta}}/cancelar")
def cancelar(
    id_proposta: Id,
    quem: Acoes,
    cliente: Granatech,
    fabrica: Fabrica,
    corpo: Annotated[dict[str, Any] | None, Body()] = None,
) -> JSONResponse:
    _proposta_da_integracao(fabrica, id_proposta, quem)
    status, resposta = _repassar(
        cliente,
        "POST",
        "/propostas/{id}/cancelar",
        f"/propostas/{id_proposta}/cancelar",
        json=corpo,
    )
    return _resposta(status, resposta)


@router.patch(f"{GRANATECH}/propostas/{{id_proposta}}/dados-bancarios")
def dados_bancarios(
    id_proposta: Id,
    corpo: Corpo,
    request: Request,
    quem: Acoes,
    cliente: Granatech,
    fabrica: Fabrica,
) -> JSONResponse:
    if not get_settings(request).granatech_dados_bancarios_ativo:
        raise HTTPException(status_code=503, detail="correção de conta desligada")
    _proposta_da_integracao(fabrica, id_proposta, quem)
    status, resposta = _repassar(
        cliente,
        "PATCH",
        "/propostas/{id}/dados-bancarios",
        f"/propostas/{id_proposta}/dados-bancarios",
        json=corpo,
    )
    return _resposta(status, resposta)
