"""Configuração da aplicação e constantes do agente.

As variáveis de ambiente usam o prefixo ``SATURDAY_`` e podem vir de um arquivo
``.env``. As constantes no fim do módulo são valores de regra/negócio e não
devem ser sobrescritas por ambiente sem revisão.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração carregada do ambiente com o prefixo ``SATURDAY_``."""

    model_config = SettingsConfigDict(
        env_prefix="SATURDAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "prod", "pytest"] = "dev"
    log_level: str = "INFO"
    api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    vision_model: str = ""
    jev_model: str = "typesafe/jev-1.13"
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")
    anexo_dominios: Annotated[list[str], NoDecode] = Field(default_factory=list)
    checkpoint_path: Path = Path("data/checkpoints.sqlite")
    retencao_extrato_dias: int = 30
    handoff_auto_release_horas: int = 0

    @field_validator("anexo_dominios", mode="before")
    @classmethod
    def _lista_por_virgula(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [item.strip() for item in valor.split(",") if item.strip()]
        return valor

    def validar_para_subir(self) -> None:
        """Interrompe a subida quando falta configuração obrigatória."""

        if self.environment != "pytest":
            obrigatorias = {
                "SATURDAY_OPENROUTER_API_KEY": self.openrouter_api_key.get_secret_value(),
                "SATURDAY_LLM_MODEL": self.llm_model,
                "SATURDAY_VISION_MODEL": self.vision_model,
            }
            faltando = [nome for nome, valor in obrigatorias.items() if not valor]
            if faltando:
                raise RuntimeError(
                    "Configuração obrigatória ausente: "
                    + ", ".join(faltando)
                    + ". Preencha o .env ou desligue a validação com "
                    "SATURDAY_ENVIRONMENT=pytest."
                )

        if self.environment == "prod" and not self.api_key.get_secret_value():
            raise RuntimeError("SATURDAY_API_KEY é obrigatória quando SATURDAY_ENVIRONMENT=prod.")

        if (
            self.webhook_url
            and not self.webhook_secret.get_secret_value()
            and self.environment != "pytest"
        ):
            raise RuntimeError(
                "SATURDAY_WEBHOOK_SECRET é obrigatória quando SATURDAY_WEBHOOK_URL está definida."
            )


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração do processo (uma única instância)."""

    return Settings()


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
