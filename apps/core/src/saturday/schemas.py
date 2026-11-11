"""Schemas do contrato HTTP."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

MIME_TYPES = Literal[
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
]

CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9_.:@+\-]+$"

UFS = frozenset(
    {
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    }
)

Intent = Literal["duvida", "suporte", "humano"]
Publico = Literal["clt", "inss", "servidor_publico", "autonomo", "indefinido"]
HandoffReason = Literal[
    "pediu_humano",
    "sem_resposta",
    "hiscon_nao_conferiu",
    "extrato_ilegivel_repetido",
    "idade_fora_regra",
    "idade_prazo_96",
    "especie_nao_atendida",
    "sem_portabilidade",
    "aceitou_portabilidade",
    "dados_cliente_nao_informados",
    "erro_interno",
    # Ramo CLT (Fase 5).
    "aceite_clt",
    "mudou_publico",
    "dado_invalido_repetido",
    "brasilapi_indisponivel",
    "granatech_indisponivel",
    "sem_consentimento",
    "termo_falhou",
    "cota_esgotada",
    "consulta_com_erro",
    "acima_do_teto",
    "limite_simulacoes",
]

MotivoContrato = Literal[
    "ok",
    "ilegivel",
    "nao_ativo",
    "ja_c6",
    "banco_nao_porta",
    "pagas_insuficientes",
    "taxa_abaixo_c6",
    "sem_tabela",
    "abaixo_minimo_c6",
    "troco_baixo",
]

MotivoPortabilidade = Literal[
    "idade_fora_regra",
    "idade_prazo_96",
    "especie_nao_atendida",
    "hiscon_nao_conferiu",
    "dados_cliente_nao_informados",
]

ConversationStatus = Literal["in_progress", "answered", "handoff"]
AguardandoColeta = Literal["data_nascimento", "uf"]


class Attachment(BaseModel):
    """Origem do anexo: `url` ou `base64` na entrada; `chave` já arquivado."""

    model_config = ConfigDict(extra="ignore")

    url: HttpUrl | None = None
    base64: str | None = Field(default=None, max_length=14_000_000)
    chave: str | None = Field(default=None, max_length=512)
    mime_type: MIME_TYPES

    @model_validator(mode="after")
    def exatamente_uma_origem(self) -> Attachment:
        origens = (self.url, self.base64, self.chave)
        if sum(origem is not None for origem in origens) != 1:
            raise ValueError("attachment deve ter exatamente uma origem: url, base64 ou chave")
        return self


class Cliente(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_nascimento: date | None = None
    uf: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("uf", mode="before")
    @classmethod
    def _uf(cls, valor: object) -> object:
        if valor is None:
            return None
        if not isinstance(valor, str):
            raise ValueError("UF inválida")
        texto = valor.strip().upper()
        if texto not in UFS:
            raise ValueError("UF inválida")
        return texto


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=CONVERSATION_ID_PATTERN,
    )
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(default="", max_length=4000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)
    cliente: Cliente | None = None


class FaixaResultado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min: float = 0.0
    max: float = 0.0


class ContratoResultado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    banco_codigo: str = ""
    banco: str = ""
    situacao: str = ""
    parcela: float | None = None
    taxa_origem: float | None = None
    qtd_parcelas: int | None = None
    pagas: int | None = None
    restantes: int | None = None
    saldo_estimado: float | None = None
    tabela_refin: str | None = None
    taxa_refin: float | None = None
    valor_liberado: float | None = None
    troco: float | None = None
    desconto_margem: float | None = None
    elegivel: bool = False
    motivo: MotivoContrato = "ilegivel"
    alerta: str | None = None
    troco_faixa: FaixaResultado = Field(default_factory=FaixaResultado)


class PortabilityResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = False
    motivo: MotivoPortabilidade | None = None
    prazo: int = 0
    beneficio_bloqueado: bool = False
    alerta_webplus: bool = False
    troco_total: float = 0.0
    troco_faixa: FaixaResultado = Field(default_factory=FaixaResultado)
    contratos: list[ContratoResultado] = Field(default_factory=list)


class AgentReply(BaseModel):
    event: Literal["agent.reply"] = "agent.reply"
    conversation_id: str
    answer: str
    status: Literal["answered", "handoff", "with_human", "duplicate"]
    intent: Intent | None = None
    publico: Publico | None = None
    handoff_reason: HandoffReason | None = None
    portability_result: PortabilityResult | None = None
    timestamp: datetime


class AcceptedReply(BaseModel):
    conversation_id: str
    status: Literal["accepted"] = "accepted"


class ConversationState(BaseModel):
    conversation_id: str
    status: ConversationStatus
    handoff_reason: str | None = None
    handoff_em: str | None = None
    oferta_pendente: bool = False
    aguardando: AguardandoColeta | None = None


class ReleaseReply(BaseModel):
    conversation_id: str
    status: Literal["in_progress"] = "in_progress"
