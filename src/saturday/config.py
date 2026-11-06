"""Configurações do agente.

As variáveis de ambiente são lidas no momento do uso (e não na importação)
para que os testes possam trocá-las com ``monkeypatch``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Limites e timeouts.
JEV_INTENT_THRESHOLD = 0.8
JEV_TIMEOUT_S = 5
LLM_TIMEOUT_S = 30
LLM_TEMPERATURE = 0
HISTORY_MAX_MESSAGES = 10
WEBHOOK_TIMEOUT_S = 10
ANEXO_MAX_MB = 10
ANEXO_TIMEOUT_S = 15
MIME_ACEITOS = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

# Fuso e horário de operação.
TZ_OPERACAO = "America/Sao_Paulo"
TZ_EQUIPE = "America/Campo_Grande"


# Segunda a sexta, das 8h às 17h.
@dataclass(frozen=True)
class HorarioEquipe:
    dias: frozenset[int]
    inicio: int
    fim: int


HORARIO_EQUIPE = HorarioEquipe(dias=frozenset({0, 1, 2, 3, 4}), inicio=8, fim=17)


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    llm_model: str
    vision_model: str
    jev_model: str
    webhook_url: str


def get_settings() -> Settings:
    """Lê as variáveis de ambiente no momento da chamada."""

    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        vision_model=os.getenv("VISION_MODEL", ""),
        jev_model=os.getenv("JEV_MODEL", "typesafe/jev-1.13"),
        webhook_url=os.getenv("WEBHOOK_URL", ""),
    )
