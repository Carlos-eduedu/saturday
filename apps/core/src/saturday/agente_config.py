"""Modelo de IA de cada etapa: a versão vigente da configuração, ou o ambiente.

A aba Agente do painel grava versões em `config_agente`; a de maior número é a
vigente. Os clientes de IA perguntam o modelo aqui a cada chamada, então uma
troca vale a partir do próximo turno, sem redeploy. O ambiente
(`SATURDAY_*_MODEL`) é o padrão enquanto não houver versão, e a saída de
emergência se o banco falhar.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from saturday.dados.modelos import ConfigAgente
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Curto de propósito: o aviso do painel diz "a partir do próximo turno".
CACHE_S = 5.0


@dataclass(frozen=True)
class Papel:
    rotulo: str
    # Nó do grafo que usa o modelo; a transcrição roda na entrada do canal.
    no: str | None
    atributo: str
    # Escolhido no catálogo da OpenRouter (os outros têm provedor próprio).
    do_catalogo: bool
    # Modalidade de entrada que o modelo precisa aceitar, além de texto.
    exige_entrada: str | None = None


PAPEIS: dict[str, Papel] = {
    "jev": Papel("Classificação de intenção (Jev)", "classify_intent", "jev_model", False),
    "llm": Papel("Respostas pela FAQ", "generate_answer", "llm_model", True),
    "visao": Papel("Leitura do extrato (visão)", "read_statement", "vision_model", True, "image"),
    "transcricao": Papel("Transcrição de áudio", None, "transcricao_modelo", False),
    # Trocar o modelo de embeddings manda reindexar todas as fontes.
    "embeddings": Papel(
        "Busca na base de conhecimento (embeddings)", "generate_answer", "embeddings_model", False
    ),
}


def do_ambiente(settings: Settings) -> dict[str, str]:
    return {papel: getattr(settings, p.atributo) or "" for papel, p in PAPEIS.items()}


def versao_vigente(sessao: Session) -> ConfigAgente | None:
    return sessao.scalar(select(ConfigAgente).order_by(ConfigAgente.versao.desc()).limit(1))


class Modelos:
    """Resolve o modelo de cada papel. Sem fábrica (testes, chat sem banco), só o ambiente."""

    def __init__(self, settings: Settings, fabrica: Any = None) -> None:
        self._settings = settings
        self._fabrica = fabrica
        self._cache: tuple[float, dict[str, str]] | None = None

    def modelo(self, papel: str) -> str:
        return self.vigentes()[papel]

    def vigentes(self) -> dict[str, str]:
        agora = time.monotonic()
        if self._cache is not None and agora - self._cache[0] < CACHE_S:
            return self._cache[1]
        modelos = {**do_ambiente(self._settings), **self._do_banco()}
        self._cache = (agora, modelos)
        return modelos

    def fixo(self, papel: str, modelo: str) -> Modelos:
        """Cópia com um papel fixado: o botão "testar" usa o modelo antes de salvar."""

        copia = Modelos(self._settings)
        copia._cache = (float("inf"), {**self.vigentes(), papel: modelo})
        return copia

    def _do_banco(self) -> dict[str, str]:
        if self._fabrica is None:
            return {}
        try:
            with abrir_sessao(self._fabrica) as sessao:
                vigente = versao_vigente(sessao)
                return {k: v for k, v in (vigente.modelos if vigente else {}).items() if v}
        except Exception as exc:  # noqa: BLE001 - banco fora não para o atendimento
            logger.warning("config_agente_indisponivel erro=%s", type(exc).__name__)
            return {}
