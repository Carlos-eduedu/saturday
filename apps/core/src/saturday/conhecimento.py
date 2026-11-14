"""Base de conhecimento (RAG) do nó de respostas.

Fontes (texto digitado, PDF, Markdown ou TXT) entram pela aba Agente do painel.
O worker extrai o texto, quebra em trechos e grava o embedding de cada um
(OpenRouter `/api/v1/embeddings`). Na resposta, a pergunta do cliente busca os
trechos mais parecidos, que entram no prompt ao lado da FAQ fixa: o LLM continua
respondendo só com o que está ali (regra 2), e sem trecho relevante nada muda.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from saturday.agente_config import Modelos
from saturday.dados import repositorios
from saturday.dados.modelos import FonteConhecimento, TrechoConhecimento
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.metrics import registrar_chamada, uso_do_payload
from saturday.services.openrouter import OpenRouterClient, OpenRouterError
from saturday.settings import Settings
from saturday.storage.base import Storage

logger = logging.getLogger(__name__)

EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
EMBEDDINGS_TIMEOUT_S = 30.0
TRECHO_CARACTERES = 1200
SOBREPOSICAO = 200
LOTE_EMBEDDINGS = 64
MAX_TRECHOS = 2000
# Busca: poucos trechos e só os parecidos de verdade, para não diluir a FAQ.
TRECHOS_POR_PERGUNTA = 4
SIMILARIDADE_MINIMA = 0.35
TIPOS = {"texto", "pdf", "markdown", "txt"}


class ErroConhecimento(RuntimeError):
    """Falha de leitura ou indexação; a mensagem é nossa e vai para o painel."""


@dataclass(frozen=True)
class Trecho:
    titulo: str
    texto: str
    similaridade: float


# ------------------------------------------------------------------ texto


def extrair_texto(tipo: str, dados: bytes) -> str:
    if tipo == "pdf":
        try:
            leitor = PdfReader(io.BytesIO(dados))
            paginas = [pagina.extract_text() or "" for pagina in leitor.pages]
        except (PdfReadError, ValueError, KeyError) as exc:
            raise ErroConhecimento("não deu para ler o PDF") from exc
        texto = "\n\n".join(paginas)
    else:
        try:
            texto = dados.decode("utf-8")
        except UnicodeDecodeError:
            texto = dados.decode("latin-1")
    texto = re.sub(r"[ \t]+", " ", texto.replace("\r\n", "\n"))
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if not texto:
        raise ErroConhecimento(
            "a fonte não tem texto (PDF escaneado precisa de texto selecionável)"
        )
    return texto


def quebrar(texto: str) -> list[str]:
    """Trechos de até ``TRECHO_CARACTERES``, cortados em parágrafo quando dá,
    com ``SOBREPOSICAO`` do fim do anterior para não partir uma resposta ao meio."""

    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    trechos: list[str] = []
    atual = ""
    for paragrafo in paragrafos:
        while len(paragrafo) > TRECHO_CARACTERES:
            if atual:
                trechos.append(atual)
                atual = ""
            corte = paragrafo.rfind(" ", 0, TRECHO_CARACTERES)
            corte = corte if corte > TRECHO_CARACTERES // 2 else TRECHO_CARACTERES
            trechos.append(paragrafo[:corte].strip())
            paragrafo = paragrafo[max(0, corte - SOBREPOSICAO) :].strip()
        if atual and len(atual) + 2 + len(paragrafo) > TRECHO_CARACTERES:
            trechos.append(atual)
            atual = atual[-SOBREPOSICAO:].split(" ", 1)[-1] + "\n\n" + paragrafo
        else:
            atual = f"{atual}\n\n{paragrafo}" if atual else paragrafo
    if atual:
        trechos.append(atual)
    return trechos


# ------------------------------------------------------------------ serviço


class Conhecimento:
    def __init__(
        self,
        http: httpx.Client,
        settings: Settings,
        fabrica: sessionmaker[Session] | None,
        modelos: Modelos | None = None,
    ) -> None:
        self._openrouter = OpenRouterClient(http, settings.openrouter_api_key.get_secret_value())
        self._tem_chave = bool(settings.openrouter_api_key.get_secret_value())
        self._fabrica = fabrica
        self._modelos = modelos or Modelos(settings, fabrica)

    @property
    def modelo(self) -> str:
        return self._modelos.modelo("embeddings")

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        modelo = self.modelo
        if not self._tem_chave or not modelo:
            raise ErroConhecimento("embeddings não configurados")
        inicio = time.monotonic()
        try:
            dados = self._openrouter.post_json(
                EMBEDDINGS_URL, {"model": modelo, "input": textos}, EMBEDDINGS_TIMEOUT_S
            )
            itens = sorted(dados["data"], key=lambda d: d.get("index", 0))
            vetores = [[float(x) for x in item["embedding"]] for item in itens]
        except (OpenRouterError, KeyError, TypeError, ValueError) as exc:
            registrar_chamada(
                "embeddings", (time.monotonic() - inicio) * 1000, status="erro", modelo=modelo
            )
            raise ErroConhecimento(f"embeddings falharam ({type(exc).__name__})") from exc
        if len(vetores) != len(textos):
            raise ErroConhecimento("embeddings vieram incompletos")
        registrar_chamada(
            "embeddings",
            (time.monotonic() - inicio) * 1000,
            status="ok",
            modelo=modelo,
            **uso_do_payload(dados),
        )
        return vetores

    def buscar(self, pergunta: str) -> list[Trecho]:
        """Trechos parecidos com a pergunta. Qualquer falha vira lista vazia: a FAQ fixa segue."""

        if self._fabrica is None or not pergunta.strip():
            return []
        try:
            with abrir_sessao(self._fabrica) as sessao:
                tem_fonte = sessao.scalar(
                    select(TrechoConhecimento.id)
                    .join(FonteConhecimento)
                    .where(
                        FonteConhecimento.status == "pronta",
                        TrechoConhecimento.modelo == self.modelo,
                    )
                    .limit(1)
                )
            if tem_fonte is None:
                return []
            [vetor] = self.embeddings([pergunta[:2000]])
            with abrir_sessao(self._fabrica) as sessao:
                linhas = sessao.execute(
                    text(
                        """
                        SELECT f.titulo, t.texto,
                               1 - (t.embedding <=> CAST(:q AS vector)) AS similaridade
                          FROM trechos_conhecimento t
                          JOIN fontes_conhecimento f ON f.id = t.fonte_id
                         WHERE f.status = 'pronta' AND t.modelo = :modelo
                         ORDER BY t.embedding <=> CAST(:q AS vector)
                         LIMIT :k
                        """
                    ),
                    {
                        "q": "[" + ",".join(repr(x) for x in vetor) + "]",
                        "modelo": self.modelo,
                        "k": TRECHOS_POR_PERGUNTA,
                    },
                ).all()
        except Exception as exc:  # noqa: BLE001 - busca fora não para a resposta
            logger.warning("busca_conhecimento_falhou erro=%s", type(exc).__name__)
            return []
        return [
            Trecho(titulo, texto_, float(sim))
            for titulo, texto_, sim in linhas
            if sim is not None and float(sim) >= SIMILARIDADE_MINIMA
        ]

    def indexar_pendente(self, storage: Storage) -> bool:
        """Indexa uma fonte pendente (worker). Devolve se havia alguma."""

        if self._fabrica is None:
            return False
        with abrir_sessao(self._fabrica) as sessao:
            fonte = sessao.scalar(
                select(FonteConhecimento)
                .where(FonteConhecimento.status == "pendente")
                .order_by(FonteConhecimento.atualizada_em)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if fonte is None:
                return False
            fonte.status = "indexando"
            fonte.erro = None
            fonte_id, tipo = fonte.id, fonte.tipo
            texto_digitado, chave = fonte.texto, fonte.arquivo_chave
            repositorios.notificar(sessao, "agente")

        try:
            dados = (texto_digitado or "").encode() if chave is None else storage.ler(chave)
            trechos = quebrar(extrair_texto(tipo, dados))
            if len(trechos) > MAX_TRECHOS:
                raise ErroConhecimento(f"fonte grande demais ({len(trechos)} trechos)")
            modelo = self.modelo
            vetores: list[list[float]] = []
            for i in range(0, len(trechos), LOTE_EMBEDDINGS):
                vetores += self.embeddings(trechos[i : i + LOTE_EMBEDDINGS])
        except Exception as exc:  # noqa: BLE001 - toda falha vira status visível
            motivo = str(exc) if isinstance(exc, ErroConhecimento) else type(exc).__name__
            logger.warning("indexacao_falhou fonte=%s erro=%s", fonte_id, type(exc).__name__)
            self._marcar(fonte_id, status="erro", erro=motivo[:200])
            return True

        with abrir_sessao(self._fabrica) as sessao:
            fonte = sessao.get(FonteConhecimento, fonte_id, with_for_update=True)
            # Editada ou removida durante a indexação: o resultado já não vale.
            if fonte is None or fonte.status != "indexando":
                return True
            sessao.execute(
                delete(TrechoConhecimento).where(TrechoConhecimento.fonte_id == fonte_id)
            )
            sessao.add_all(
                TrechoConhecimento(
                    fonte_id=fonte_id, ordem=i, texto=trecho, embedding=vetor, modelo=modelo
                )
                for i, (trecho, vetor) in enumerate(zip(trechos, vetores, strict=True))
            )
            fonte.status = "pronta"
            fonte.trechos = len(trechos)
            fonte.modelo = modelo
            fonte.indexada_em = datetime.now(UTC)
            repositorios.notificar(sessao, "agente")
        return True

    def _marcar(self, fonte_id: Any, **campos: Any) -> None:
        if self._fabrica is None:
            return
        with abrir_sessao(self._fabrica) as sessao:
            fonte = sessao.get(FonteConhecimento, fonte_id)
            if fonte is not None and fonte.status == "indexando":
                for campo, valor in campos.items():
                    setattr(fonte, campo, valor)
                repositorios.notificar(sessao, "agente")
