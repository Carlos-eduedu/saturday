"""Schemas do contrato HTTP."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Attachment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    base64: str | None = None
    mime_type: str

    @model_validator(mode="after")
    def exatamente_uma_origem(self) -> Attachment:
        if (self.url is None) == (self.base64 is None):
            raise ValueError("attachment deve ter url ou base64, nunca os dois")
        return self


class Cliente(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_nascimento: str | None = None
    uf: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conversation_id: str = Field(min_length=1)
    message: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    cliente: Cliente | None = None


class AgentReply(BaseModel):
    event: Literal["agent.reply"] = "agent.reply"
    conversation_id: str
    answer: str
    status: Literal["answered", "handoff"]
    intent: str | None = None
    publico: str | None = None
    handoff_reason: str | None = None
    portability_result: dict[str, Any] | None = None
    timestamp: datetime
