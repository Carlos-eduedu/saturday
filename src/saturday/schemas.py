"""Schemas do contrato HTTP."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

MIME_TYPES = Literal[
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
]

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


class Attachment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: HttpUrl | None = None
    base64: str | None = Field(default=None, max_length=14_000_000)
    mime_type: MIME_TYPES

    @model_validator(mode="after")
    def exatamente_uma_origem(self) -> Attachment:
        if (self.url is None) == (self.base64 is None):
            raise ValueError("attachment deve ter url ou base64, nunca os dois")
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
        pattern=r"^[A-Za-z0-9_.:@+\-]+$",
    )
    message_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(default="", max_length=4000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)
    cliente: Cliente | None = None


class AgentReply(BaseModel):
    event: Literal["agent.reply"] = "agent.reply"
    conversation_id: str
    answer: str
    status: Literal["answered", "handoff", "with_human", "duplicate"]
    intent: str | None = None
    publico: str | None = None
    handoff_reason: str | None = None
    portability_result: dict[str, Any] | None = None
    timestamp: datetime


class AcceptedReply(BaseModel):
    conversation_id: str
    status: Literal["accepted"] = "accepted"


class ConversationState(BaseModel):
    conversation_id: str
    status: str
    handoff_reason: str | None = None
    handoff_em: str | None = None
    oferta_pendente: bool = False
    aguardando: str | None = None


class ReleaseReply(BaseModel):
    conversation_id: str
    status: Literal["in_progress"] = "in_progress"
