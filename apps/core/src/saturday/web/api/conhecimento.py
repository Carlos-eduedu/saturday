"""Aba Agente → Conhecimento: fontes da base de conhecimento (RAG).

Ver é para todos do painel; adicionar, editar, reindexar e remover exigem a
permissão "editar agente". A API só grava a fonte como pendente; quem indexa é
o worker (`conhecimento.Conhecimento.indexar_pendente`). O arquivo vem cru no
corpo, como o anexo da conversa, e vai para o storage privado.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from saturday.agent.service import AgentService
from saturday.agente_config import Modelos
from saturday.dados import repositorios
from saturday.dados.modelos import FonteConhecimento, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel.auditoria import auditar
from saturday.web.dependencies import (
    UsuarioLogado,
    editor_do_agente,
    exigir_fabrica,
    get_agent_service,
    get_settings,
    usuario_logado,
)

router = APIRouter(prefix="/admin/agente/conhecimento", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(exigir_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]
Editor = Annotated[UsuarioLogado, Depends(editor_do_agente)]
Servico = Annotated[AgentService, Depends(get_agent_service)]

MAX_TEXTO = 200_000
MAX_ARQUIVO = 10 * 1024 * 1024
# Extensão → tipo da fonte. O PDF ainda é conferido pela assinatura do arquivo.
EXTENSOES = {"pdf": "pdf", "md": "markdown", "markdown": "markdown", "txt": "txt"}


class NovoTexto(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)
    texto: str = Field(min_length=1, max_length=MAX_TEXTO)


class Edicao(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=120)
    texto: str | None = Field(default=None, min_length=1, max_length=MAX_TEXTO)


def _json(f: FonteConhecimento, autores: dict[Any, str], vigente: str) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "titulo": f.titulo,
        "tipo": f.tipo,
        "arquivo_nome": f.arquivo_nome,
        "tamanho": f.tamanho,
        "status": f.status,
        "erro": f.erro,
        "trechos": f.trechos,
        "modelo": f.modelo,
        # Indexada com outro modelo de embeddings: não entra na busca até reindexar.
        "desatualizada": f.status == "pronta" and f.modelo != vigente,
        "autor": autores.get(f.autor_id),
        "criada_em": f.criada_em,
        "atualizada_em": f.atualizada_em,
        "indexada_em": f.indexada_em,
        "editavel": f.tipo == "texto",
    }


def _buscar(sessao: Session, fonte_id: uuid.UUID) -> FonteConhecimento:
    fonte = sessao.get(FonteConhecimento, fonte_id, with_for_update=True)
    if fonte is None:
        raise HTTPException(status_code=404, detail="fonte não encontrada")
    return fonte


@router.get("")
def listar(request: Request, usuario: Logado, fabrica: Fabrica) -> dict[str, Any]:
    vigente = Modelos(get_settings(request), fabrica).modelo("embeddings")
    with abrir_sessao(fabrica) as sessao:
        fontes = list(
            sessao.scalars(select(FonteConhecimento).order_by(FonteConhecimento.criada_em.desc()))
        )
        ids = {f.autor_id for f in fontes if f.autor_id}
        autores: dict[Any, str] = (
            dict(
                sessao.execute(
                    select(UsuarioPainel.id, UsuarioPainel.nome).where(UsuarioPainel.id.in_(ids))
                ).all()
            )
            if ids
            else {}
        )
        return {
            "fontes": [_json(f, autores, vigente) for f in fontes],
            "modelo_embeddings": vigente,
            "pode_editar": usuario.pode_editar_agente,
        }


@router.post("/texto", status_code=201)
def adicionar_texto(dados: NovoTexto, usuario: Editor, fabrica: Fabrica) -> dict[str, str]:
    with abrir_sessao(fabrica) as sessao:
        fonte = FonteConhecimento(
            titulo=dados.titulo.strip(),
            tipo="texto",
            texto=dados.texto,
            tamanho=len(dados.texto.encode()),
            status="pendente",
            autor_id=usuario.id,
        )
        sessao.add(fonte)
        sessao.flush()
        auditar(sessao, usuario.id, "conhecimento_adicionar", str(fonte.id), {"tipo": "texto"})
        repositorios.notificar(sessao, "agente")
        return {"id": str(fonte.id)}


@router.post("/arquivo", status_code=201)
async def adicionar_arquivo(
    request: Request,
    usuario: Editor,
    fabrica: Fabrica,
    service: Servico,
    titulo: Annotated[str, Query(min_length=1, max_length=120)],
    nome: Annotated[str, Query(min_length=1, max_length=200)],
) -> dict[str, str]:
    if service.storage is None:
        raise HTTPException(status_code=503, detail="storage indisponível")
    # Só o nome: um caminho vindo do navegador não entra na fonte.
    nome = nome.replace("\\", "/").rsplit("/", 1)[-1].strip()
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    tipo = EXTENSOES.get(extensao)
    if tipo is None:
        raise HTTPException(status_code=415, detail="aceita só PDF, Markdown (.md) ou TXT")
    dados = await request.body()
    if not dados:
        raise HTTPException(status_code=422, detail="arquivo vazio")
    if len(dados) > MAX_ARQUIVO:
        raise HTTPException(status_code=413, detail="arquivo acima de 10 MB")
    if tipo == "pdf" and not dados.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="o arquivo não é um PDF")

    fonte_id = uuid.uuid4()
    mime = {"pdf": "application/pdf", "markdown": "text/markdown"}.get(tipo, "text/plain")
    chave = await run_in_threadpool(
        service.storage.salvar,
        dados,
        mime_type=mime,
        chave=f"conhecimento/{fonte_id}.{extensao}",
    )
    with abrir_sessao(fabrica) as sessao:
        sessao.add(
            FonteConhecimento(
                id=fonte_id,
                titulo=titulo.strip(),
                tipo=tipo,
                arquivo_chave=chave,
                arquivo_nome=nome,
                tamanho=len(dados),
                status="pendente",
                autor_id=usuario.id,
            )
        )
        auditar(sessao, usuario.id, "conhecimento_adicionar", str(fonte_id), {"tipo": tipo})
        repositorios.notificar(sessao, "agente")
    return {"id": str(fonte_id)}


@router.patch("/{fonte_id}", status_code=204)
def editar(fonte_id: uuid.UUID, dados: Edicao, usuario: Editor, fabrica: Fabrica) -> Response:
    """Título de qualquer fonte; texto só da digitada (arquivo: remova e envie outro)."""

    with abrir_sessao(fabrica) as sessao:
        fonte = _buscar(sessao, fonte_id)
        mudou: list[str] = []
        if dados.titulo is not None and dados.titulo.strip() != fonte.titulo:
            fonte.titulo = dados.titulo.strip()
            mudou.append("titulo")
        if dados.texto is not None and dados.texto != fonte.texto:
            if fonte.tipo != "texto":
                raise HTTPException(status_code=422, detail="o texto de um arquivo não se edita")
            fonte.texto = dados.texto
            fonte.tamanho = len(dados.texto.encode())
            fonte.status = "pendente"
            mudou.append("texto")
        if mudou:
            auditar(sessao, usuario.id, "conhecimento_editar", str(fonte_id), {"campos": mudou})
            repositorios.notificar(sessao, "agente")
    return Response(status_code=204)


@router.post("/{fonte_id}/reindexar", status_code=204)
def reindexar(fonte_id: uuid.UUID, usuario: Editor, fabrica: Fabrica) -> Response:
    with abrir_sessao(fabrica) as sessao:
        fonte = _buscar(sessao, fonte_id)
        fonte.status = "pendente"
        fonte.erro = None
        auditar(sessao, usuario.id, "conhecimento_reindexar", str(fonte_id))
        repositorios.notificar(sessao, "agente")
    return Response(status_code=204)


@router.post("/reindexar", status_code=200)
def reindexar_todas(usuario: Editor, fabrica: Fabrica) -> dict[str, int]:
    """Depois de trocar o modelo de embeddings: tudo volta para a fila."""

    with abrir_sessao(fabrica) as sessao:
        n = len(
            sessao.scalars(
                update(FonteConhecimento)
                .where(FonteConhecimento.status != "pendente")
                .values(status="pendente", erro=None)
                .returning(FonteConhecimento.id)
            ).all()
        )
        auditar(sessao, usuario.id, "conhecimento_reindexar", "todas", {"fontes": n})
        repositorios.notificar(sessao, "agente")
    return {"fontes": n}


@router.delete("/{fonte_id}", status_code=204)
async def remover(
    fonte_id: uuid.UUID, usuario: Editor, fabrica: Fabrica, service: Servico
) -> Response:
    """Some da busca na hora (os trechos caem junto); o arquivo sai do storage."""

    def apagar() -> str | None:
        with abrir_sessao(fabrica) as sessao:
            fonte = _buscar(sessao, fonte_id)
            chave = fonte.arquivo_chave
            auditar(
                sessao, usuario.id, "conhecimento_remover", str(fonte_id), {"titulo": fonte.titulo}
            )
            sessao.delete(fonte)
            repositorios.notificar(sessao, "agente")
            return chave

    chave = await run_in_threadpool(apagar)
    if chave and service.storage is not None:
        await run_in_threadpool(service.storage.apagar, chave)
    return Response(status_code=204)
