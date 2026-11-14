"""Aba Agente: modelos por etapa, catálogo da OpenRouter, teste e versões.

Ver é para todos do painel. Salvar, restaurar e atualizar o catálogo exigem a
permissão "editar agente" (`usuarios_painel.pode_editar_agente`); testar um
modelo faz uma chamada paga e é só do gestor. Toda ação grava `auditoria`.
Uma versão nova vale a partir do próximo turno (`agente_config.Modelos`).
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from saturday.agente_config import PAPEIS, Modelos, do_ambiente, versao_vigente
from saturday.dados import repositorios
from saturday.dados.modelos import CatalogoModelos, ConfigAgente, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import iniciar_metricas
from saturday.painel.auditoria import auditar
from saturday.services.jev import JevClient, JevError
from saturday.services.llm import OPENROUTER_CHAT_URL, LLMClient, LLMError
from saturday.services.openrouter import OpenRouterClient, OpenRouterError
from saturday.web.dependencies import (
    UsuarioLogado,
    editor_do_agente,
    exigir_fabrica,
    gestor_com_csrf,
    get_settings,
    usuario_logado,
)

router = APIRouter(prefix="/admin/agente", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
Editor = Annotated[UsuarioLogado, Depends(editor_do_agente)]
GestorCsrf = Annotated[UsuarioLogado, Depends(gestor_com_csrf)]

CATALOGO_URL = "https://openrouter.ai/api/v1/models"
CATALOGO_TIMEOUT_S = 15.0
TESTE_TIMEOUT_S = 30.0
LATENCIA_DIAS = 7
MODELO_VALIDO = re.compile(r"^[\w.:/@+-]{1,128}$")
# Parâmetros que as chamadas do Saturday usam: o modelo precisa aceitá-los.
JSON_ESTRUTURADO = {"response_format", "structured_outputs"}


# ------------------------------------------------------------------ leitura


def _por_milhao(valor: Any) -> float | None:
    """A OpenRouter dá o preço por token, em texto (``"0.0000025"``)."""

    try:
        preco = Decimal(str(valor))
    except InvalidOperation, ValueError:
        return None
    return None if preco < 0 else float(preco * 1_000_000)


def _normalizar(bruto: dict[str, Any]) -> dict[str, Any] | None:
    ident = bruto.get("id")
    if not isinstance(ident, str) or not MODELO_VALIDO.match(ident):
        return None
    preco = bruto.get("pricing") or {}
    arquitetura = bruto.get("architecture") or {}
    provedor = bruto.get("top_provider") or {}
    return {
        "id": ident,
        "nome": str(bruto.get("name") or ident)[:120],
        "contexto": bruto.get("context_length"),
        "max_saida": provedor.get("max_completion_tokens"),
        "entrada": list(arquitetura.get("input_modalities") or ["text"]),
        "saida": list(arquitetura.get("output_modalities") or ["text"]),
        "preco_entrada": _por_milhao(preco.get("prompt")),
        "preco_saida": _por_milhao(preco.get("completion")),
        "preco_imagem": _por_milhao(preco.get("image")),
        "parametros": list(bruto.get("supported_parameters") or []),
    }


def _latencias(sessao: Session) -> dict[str, dict[str, float]]:
    """Latência medida nas nossas chamadas (a OpenRouter não publica), por modelo."""

    linhas = sessao.execute(
        text(
            """
            SELECT c->>'modelo' AS modelo,
                   avg((c->>'latencia_ms')::float) AS media,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY (c->>'latencia_ms')::float) AS p95,
                   count(*) AS chamadas
              FROM turnos, jsonb_array_elements(turnos.chamadas) AS c
             WHERE turnos.criado_em >= :desde AND c ? 'modelo'
             GROUP BY 1
            """
        ),
        {"desde": datetime.now(UTC) - timedelta(days=LATENCIA_DIAS)},
    ).all()
    return {
        m: {"media_ms": round(media), "p95_ms": round(p95), "chamadas": int(n)}
        for m, media, p95, n in linhas
    }


def _em_andamento(sessao: Session) -> int:
    """Travas de conversa seguras agora: cada uma é um turno rodando."""

    return int(
        sessao.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted"))
        or 0
    )


def _versao_json(v: ConfigAgente, autores: dict[Any, str]) -> dict[str, Any]:
    return {
        "versao": v.versao,
        "modelos": v.modelos,
        "nota": v.nota,
        "restaurada_de": v.restaurada_de,
        "autor": autores.get(v.autor_id),
        "criada_em": v.criada_em,
    }


def _autores(sessao: Session, versoes: list[ConfigAgente]) -> dict[Any, str]:
    ids = {v.autor_id for v in versoes if v.autor_id}
    if not ids:
        return {}
    linhas = sessao.execute(
        select(UsuarioPainel.id, UsuarioPainel.nome).where(UsuarioPainel.id.in_(ids))
    ).all()
    return dict(linhas)


@router.get("/modelos")
def modelos(request: Request, usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    settings = get_settings(request)
    ambiente = do_ambiente(settings)
    with abrir_sessao(fabrica) as sessao:
        vigente = versao_vigente(sessao)
        catalogo = sessao.get(CatalogoModelos, 1)
        autores = _autores(sessao, [vigente] if vigente else [])
        latencia = _latencias(sessao)
        em_andamento = _em_andamento(sessao)
        salvos = vigente.modelos if vigente else {}
        return {
            "vigente": _versao_json(vigente, autores) if vigente else None,
            "papeis": [
                {
                    "papel": nome,
                    "rotulo": p.rotulo,
                    "no": p.no,
                    "do_catalogo": p.do_catalogo,
                    "exige_entrada": p.exige_entrada,
                    "modelo": salvos.get(nome) or ambiente[nome],
                    "origem": "versao" if salvos.get(nome) else "ambiente",
                    "variavel": f"SATURDAY_{p.atributo.upper()}",
                }
                for nome, p in PAPEIS.items()
            ],
            "catalogo": {
                "fonte": catalogo.fonte if catalogo else CATALOGO_URL,
                "buscado_em": catalogo.buscado_em if catalogo else None,
                "modelos": catalogo.modelos if catalogo else [],
            },
            "transcricao_provedor": httpx.URL(settings.transcricao_base_url).host,
            "latencia": latencia,
            "latencia_dias": LATENCIA_DIAS,
            "em_andamento": em_andamento,
            "pode_editar": usuario.pode_editar_agente,
            "pode_testar": usuario.gestor,
        }


# ------------------------------------------------------------------ catálogo


@router.post("/catalogo/atualizar")
def atualizar_catalogo(request: Request, usuario: Editor, fabrica: Fabrica) -> dict[str, Any]:
    """Lê o catálogo público da OpenRouter e guarda com a data da leitura."""

    http: httpx.Client = request.app.state.http
    try:
        resposta = http.get(CATALOGO_URL, timeout=CATALOGO_TIMEOUT_S)
        resposta.raise_for_status()
        dados = resposta.json().get("data")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=502, detail=f"OpenRouter não respondeu ({type(exc).__name__})"
        ) from exc
    if not isinstance(dados, list):
        raise HTTPException(status_code=502, detail="OpenRouter devolveu um catálogo inválido")
    lista = [m for m in (_normalizar(b) for b in dados if isinstance(b, dict)) if m]
    lista.sort(key=lambda m: m["id"])

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get(CatalogoModelos, 1)
        if linha is None:
            linha = CatalogoModelos(id=1, fonte=CATALOGO_URL, modelos=lista)
            sessao.add(linha)
        else:
            linha.modelos = lista
            linha.fonte = CATALOGO_URL
            linha.buscado_em = datetime.now(UTC)
        auditar(sessao, usuario.id, "agente_catalogo", detalhe={"modelos": len(lista)})
        repositorios.notificar(sessao, "agente")
    return {"modelos": len(lista)}


# ------------------------------------------------------------------ teste


class Teste(BaseModel):
    papel: str
    modelo: str = Field(max_length=128)
    texto: str = Field(min_length=1, max_length=2000)


@router.post("/modelos/testar")
def testar(dados: Teste, request: Request, usuario: GestorCsrf, fabrica: Fabrica) -> dict[str, Any]:
    """Chamada real e paga ao modelo, com o mesmo prompt do atendimento quando dá.

    Classificação e FAQ passam pelo cliente de verdade; visão recebe só o texto
    (sem anexo); transcrição precisa de áudio e não tem teste aqui.
    """

    if dados.papel not in PAPEIS:
        raise HTTPException(status_code=422, detail="etapa desconhecida")
    if not MODELO_VALIDO.match(dados.modelo):
        raise HTTPException(status_code=422, detail="id de modelo inválido")
    if dados.papel == "transcricao":
        raise HTTPException(status_code=422, detail="o teste de transcrição precisa de áudio")

    settings = get_settings(request)
    http: httpx.Client = request.app.state.http
    modelos = Modelos(settings).fixo(dados.papel, dados.modelo)
    metricas = iniciar_metricas()
    inicio = time.monotonic()
    resposta: str | None = None
    detalhe: dict[str, Any] | None = None
    erro: str | None = None
    try:
        if dados.papel == "jev":
            r = JevClient(http, settings, modelos).classify(dados.texto)
            detalhe = {
                "intencao": r.intent,
                "confianca": r.intent_confidence,
                "publico": r.publico,
                "confianca_publico": r.publico_confidence,
            }
        elif dados.papel == "llm":
            r_llm = LLMClient(http, settings, modelos).responder(
                [{"role": "user", "content": dados.texto}]
            )
            resposta = r_llm.resposta
            detalhe = {"resolvido": r_llm.resolvido}
        else:
            bruto = OpenRouterClient(
                http, settings.openrouter_api_key.get_secret_value()
            ).post_json(
                OPENROUTER_CHAT_URL,
                {
                    "model": dados.modelo,
                    "messages": [{"role": "user", "content": dados.texto}],
                    "max_tokens": 400,
                    "usage": {"include": True},
                },
                TESTE_TIMEOUT_S,
            )
            resposta = bruto["choices"][0]["message"]["content"]
    except (JevError, LLMError, OpenRouterError, KeyError, IndexError, TypeError) as exc:
        erro = type(exc).__name__
    latencia_ms = round((time.monotonic() - inicio) * 1000)
    chamada = metricas.chamadas[-1] if metricas.chamadas else None

    with abrir_sessao(fabrica) as sessao:
        # Só etapa e modelo: o texto digitado e a resposta não vão para a auditoria.
        auditar(
            sessao,
            usuario.id,
            "agente_modelo_testado",
            dados.papel,
            {"modelo": dados.modelo, "erro": erro},
        )
    return {
        "ok": erro is None,
        "erro": erro,
        "resposta": resposta[:4000] if isinstance(resposta, str) else None,
        "detalhe": detalhe,
        "latencia_ms": latencia_ms,
        "custo_usd": chamada.custo_usd if chamada else None,
        "tokens_entrada": chamada.tokens_entrada if chamada else None,
        "tokens_saida": chamada.tokens_saida if chamada else None,
    }


# ------------------------------------------------------------------ versões


class NovaVersao(BaseModel):
    # A versão que a pessoa estava vendo: outra pessoa pode ter salvo antes.
    versao_base: int | None
    modelos: dict[str, str]
    nota: str | None = Field(default=None, max_length=280)


class Restaurar(BaseModel):
    versao_base: int | None


def _validar(modelos: dict[str, str], catalogo: CatalogoModelos | None) -> dict[str, str]:
    desconhecidos = set(modelos) - PAPEIS.keys()
    if desconhecidos:
        raise HTTPException(status_code=422, detail=f"etapa desconhecida: {sorted(desconhecidos)}")
    limpos = {papel: valor.strip() for papel, valor in modelos.items()}
    por_id = {m["id"]: m for m in (catalogo.modelos if catalogo else [])}
    for papel, valor in limpos.items():
        # Vazio: vale a variável de ambiente da etapa (`agente_config.Modelos`).
        if not valor:
            continue
        if not MODELO_VALIDO.match(valor):
            raise HTTPException(status_code=422, detail=f"{papel}: id de modelo inválido")
        regra = PAPEIS[papel]
        if not regra.do_catalogo or not por_id:
            continue
        info = por_id.get(valor)
        if info is None:
            raise HTTPException(
                status_code=422, detail=f"{papel}: {valor} não está no catálogo da OpenRouter"
            )
        if regra.exige_entrada and regra.exige_entrada not in info["entrada"]:
            raise HTTPException(
                status_code=422, detail=f"{papel}: {valor} não aceita {regra.exige_entrada}"
            )
        if info["parametros"] and not JSON_ESTRUTURADO & set(info["parametros"]):
            raise HTTPException(
                status_code=422, detail=f"{papel}: {valor} não aceita resposta em JSON"
            )
    return limpos


def _gravar(
    sessao: Session,
    usuario: UsuarioLogado,
    versao_base: int | None,
    modelos: dict[str, str],
    nota: str | None,
    restaurada_de: int | None = None,
) -> dict[str, Any]:
    vigente = versao_vigente(sessao)
    atual = vigente.versao if vigente else None
    if versao_base != atual:
        raise HTTPException(
            status_code=409,
            detail="outra pessoa salvou uma versão nova: recarregue e confira antes de salvar",
        )
    anteriores = vigente.modelos if vigente else {}
    if modelos == anteriores:
        raise HTTPException(status_code=422, detail="nada mudou em relação à versão vigente")
    nova = ConfigAgente(
        versao=(atual or 0) + 1,
        modelos=modelos,
        nota=(nota or "").strip() or None,
        restaurada_de=restaurada_de,
        autor_id=usuario.id,
    )
    sessao.add(nova)
    try:
        with sessao.begin_nested():
            sessao.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="outra versão foi salva ao mesmo tempo"
        ) from exc
    mudou = {
        papel: [anteriores.get(papel), valor]
        for papel, valor in modelos.items()
        if anteriores.get(papel) != valor
    }
    auditar(
        sessao,
        usuario.id,
        "agente_config_restaurada" if restaurada_de else "agente_config_salva",
        str(nova.versao),
        {"mudou": mudou, "restaurada_de": restaurada_de},
    )
    repositorios.notificar(sessao, "agente")
    return {"versao": nova.versao}


@router.get("/versoes")
def versoes(_usuario: Logado, fabrica: Fabrica) -> list[dict[str, Any]]:
    with abrir_sessao(fabrica) as sessao:
        linhas = list(
            sessao.scalars(select(ConfigAgente).order_by(ConfigAgente.versao.desc()).limit(100))
        )
        autores = _autores(sessao, linhas)
        return [_versao_json(v, autores) for v in linhas]


@router.post("/versoes", status_code=201)
def salvar(
    dados: NovaVersao, request: Request, usuario: Editor, fabrica: Fabrica
) -> dict[str, Any]:
    """Grava todos os papéis: o que não veio fica como está valendo agora."""

    with abrir_sessao(fabrica) as sessao:
        base = {**do_ambiente(get_settings(request))}
        vigente = versao_vigente(sessao)
        if vigente:
            base.update({k: v for k, v in vigente.modelos.items() if v})
        modelos = _validar({**base, **dados.modelos}, sessao.get(CatalogoModelos, 1))
        return _gravar(sessao, usuario, dados.versao_base, modelos, dados.nota)


@router.post("/versoes/{versao}/restaurar", status_code=201)
def restaurar(versao: int, dados: Restaurar, usuario: Editor, fabrica: Fabrica) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        alvo = sessao.scalar(select(ConfigAgente).where(ConfigAgente.versao == versao))
        if alvo is None:
            raise HTTPException(status_code=404, detail="versão não encontrada")
        return _gravar(
            sessao,
            usuario,
            dados.versao_base,
            dict(alvo.modelos),
            f"Restaurada a versão {versao}",
            restaurada_de=versao,
        )
