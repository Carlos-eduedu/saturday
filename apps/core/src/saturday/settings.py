"""Configuração da aplicação e constantes do agente.

As variáveis de ambiente usam o prefixo ``SATURDAY_`` e podem vir de um arquivo
``.env``. As constantes no fim do módulo são valores de regra/negócio e não
devem ser sobrescritas por ambiente sem revisão.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
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

    environment: Literal["dev", "homolog", "prod", "pytest"] = "dev"
    log_level: str = "INFO"
    api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    vision_model: str = ""
    jev_model: str = "typesafe/jev-1.13"
    # Embeddings da base de conhecimento (OpenRouter `/api/v1/embeddings`).
    embeddings_model: str = "openai/text-embedding-3-small"
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")
    anexo_dominios: Annotated[list[str], NoDecode] = Field(default_factory=list)
    retencao_extrato_dias: int = 30
    handoff_auto_release_horas: int = 0

    # Postgres: estado das conversas, outbox e travas. Vazio em `pytest`.
    database_url: SecretStr = SecretStr("")

    # Storage S3 (MinIO interno ou externo) para os anexos dos clientes.
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_regiao: str = "us-east-1"

    # Outbox: quantas vezes reentregar antes de desistir e quanto esperar.
    outbox_max_tentativas: int = 6
    outbox_backoff_base_s: float = 2.0
    outbox_lote: int = 20

    # WhatsApp Cloud API (Meta). Obrigatórias fora de `pytest`.
    whatsapp_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_numeros: Annotated[list[str], NoDecode] = Field(default_factory=list)
    whatsapp_graph_url: str = "https://graph.facebook.com/v23.0"
    whatsapp_limite_midia_mb: int = 50

    # Evolution API (WhatsApp Web, não oficial): segundo canal, decisões 0009 e
    # 0010. Toda instância da Evolution do Saturday é atendida; o painel as cria.
    evolution_ativo: bool = False
    evolution_url: str = "http://evolution:8080"
    evolution_api_key: SecretStr = SecretStr("")
    evolution_webhook_token: SecretStr = SecretStr("")
    # Para onde a Evolution manda os eventos: a API pela rede interna.
    evolution_webhook_url: str = "http://api:8000/webhooks/evolution"

    # Transcrição de áudio: endpoint compatível com OpenAI (`/audio/transcriptions`).
    transcricao_api_key: SecretStr = SecretStr("")
    transcricao_modelo: str = ""
    transcricao_base_url: str = "https://api.openai.com/v1"

    # Fila de eventos: tamanho do lote e quantas tentativas antes de desistir.
    eventos_lote: int = 20
    eventos_max_tentativas: int = 8

    # Painel: assina o CSRF da sessão. Obrigatória fora de `pytest`.
    sessao_segredo: SecretStr = SecretStr("")

    # Granatech. `ativo` liga o cliente; o webhook fica sempre no ar e responde
    # 503 enquanto o token estiver vazio.
    granatech_base_url: str = "https://api-dev.granatech.com.br"
    granatech_chave_api: SecretStr = SecretStr("")
    granatech_webhook_token: SecretStr = SecretStr("")
    granatech_ativo: bool = False
    granatech_proposta_ativa: bool = False
    # TODO(granatech): corpo do PATCH de dados bancários; até lá, desligado.
    granatech_dados_bancarios_ativo: bool = False
    granatech_teto_liberado: Decimal = Decimal("6999")
    granatech_cota_mensal: int = 500
    granatech_cota_diaria: int = 20
    granatech_reaproveitar_dias: int = 30
    # TODO(granatech): confirmar o `tipo_empregador` do corpo da proposta.
    granatech_tipo_empregador: int = 1

    # Domínio dos links curtos (`https://{dominio}/l/{codigo}`), obrigatório com a
    # proposta ligada.
    dominio_publico: str = ""

    @field_validator("dominio_publico")
    @classmethod
    def _so_o_dominio(cls, valor: str) -> str:
        # Aceita a URL inteira na variável: os links já põem o https://.
        valor = valor.strip().removeprefix("https://").removeprefix("http://")
        return valor.rstrip("/")

    @field_validator("anexo_dominios", "whatsapp_numeros", mode="before")
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
                "SATURDAY_DATABASE_URL": self.database_url.get_secret_value(),
                "SATURDAY_WHATSAPP_TOKEN": self.whatsapp_token.get_secret_value(),
                "SATURDAY_WHATSAPP_APP_SECRET": self.whatsapp_app_secret.get_secret_value(),
                "SATURDAY_WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token.get_secret_value(),
                "SATURDAY_SESSAO_SEGREDO": self.sessao_segredo.get_secret_value(),
            }
            faltando = [nome for nome, valor in obrigatorias.items() if not valor]
            if faltando:
                raise RuntimeError(
                    "Configuração obrigatória ausente: "
                    + ", ".join(faltando)
                    + ". Preencha o .env ou desligue a validação com "
                    "SATURDAY_ENVIRONMENT=pytest."
                )

        # Anexo por URL ou base64 é guardado no S3; sem bucket, o anexo se perde
        # no fim do turno e a retenção não tem o que apagar.
        if (
            self.environment != "pytest"
            and self.database_url.get_secret_value()
            and not self.s3_bucket
        ):
            raise RuntimeError(
                "SATURDAY_S3_BUCKET é obrigatório quando SATURDAY_DATABASE_URL existe. "
                "Use o MinIO do compose (SATURDAY_S3_ENDPOINT vazio) ou um bucket externo."
            )

        # Fora de `dev` e `pytest` a API atende dados pessoais: sem chave, não sobe.
        if self.environment in {"homolog", "prod"} and not self.api_key.get_secret_value():
            raise RuntimeError(
                f"SATURDAY_API_KEY é obrigatória quando SATURDAY_ENVIRONMENT={self.environment}."
            )

        if self.environment != "pytest" and not self.whatsapp_numeros:
            raise RuntimeError(
                "SATURDAY_WHATSAPP_NUMEROS é obrigatória: sem um phone_number_id ativo "
                "o canal não sabe de qual número responder."
            )

        if self.granatech_ativo and self.environment != "pytest":
            faltando = [
                nome
                for nome, valor in {
                    "SATURDAY_GRANATECH_CHAVE_API": self.granatech_chave_api,
                    "SATURDAY_GRANATECH_WEBHOOK_TOKEN": self.granatech_webhook_token,
                }.items()
                if not valor.get_secret_value()
            ]
            if faltando:
                raise RuntimeError(
                    "SATURDAY_GRANATECH_ATIVO=true exige " + ", ".join(faltando) + "."
                )

        if self.evolution_ativo and self.environment != "pytest":
            faltando = [
                nome
                for nome, valor in {
                    "SATURDAY_EVOLUTION_API_KEY": self.evolution_api_key.get_secret_value(),
                    "SATURDAY_EVOLUTION_WEBHOOK_TOKEN": (
                        self.evolution_webhook_token.get_secret_value()
                    ),
                }.items()
                if not valor
            ]
            if faltando:
                raise RuntimeError(
                    "SATURDAY_EVOLUTION_ATIVO=true exige " + ", ".join(faltando) + "."
                )

        if (
            self.granatech_proposta_ativa
            and not self.dominio_publico
            and self.environment != "pytest"
        ):
            raise RuntimeError(
                "SATURDAY_GRANATECH_PROPOSTA_ATIVA=true exige SATURDAY_DOMINIO_PUBLICO "
                "(links da biometria)."
            )

        # O webhook da Granatech fica sempre no ar; sem token ele recusa tudo, e
        # fora de dev isso esconderia eventos perdidos.
        if (
            self.environment in {"homolog", "prod"}
            and not self.granatech_webhook_token.get_secret_value()
        ):
            raise RuntimeError(
                "SATURDAY_GRANATECH_WEBHOOK_TOKEN é obrigatória quando "
                f"SATURDAY_ENVIRONMENT={self.environment}."
            )

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
# Medido com o Jev real (tests/test_jev_avaliacao.py, 2026-11-12): saudações de
# verdade ficam em 0,99+, e "Ok."/"Vamos nessa."/"Entendi." chegam a 0,88.
JEV_SAUDACAO_THRESHOLD = 0.95
JEV_TIMEOUT_S = 5
LLM_TIMEOUT_S = 30
LLM_TEMPERATURE = 0
HISTORY_MAX_MESSAGES = 10
WEBHOOK_TIMEOUT_S = 10
GRANATECH_TIMEOUT_S = 15
GRANATECH_ESPERA_RETRY_S = 1.5
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
