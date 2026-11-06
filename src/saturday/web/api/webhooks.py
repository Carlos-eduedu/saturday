"""Documentação OpenAPI do webhook de saída."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header

from saturday.schemas import AgentReply

DESCRICAO_WEBHOOK = (
    "Evento enviado por `POST` para `SATURDAY_WEBHOOK_URL` ao final de um turno. "
    "O corpo é um `AgentReply`. "
    "`X-Saturday-Timestamp` são segundos Unix. "
    "`X-Saturday-Signature` é `sha256=` + HMAC-SHA256 de "
    "`timestamp + '.' + corpo`, com `SATURDAY_WEBHOOK_SECRET`. "
    "Verifique com `hmac.compare_digest` antes de consumir o evento."
)


def documentar_webhook(app: FastAPI) -> None:
    """Adiciona o evento ``agent.reply`` em ``app.webhooks`` (OpenAPI)."""

    @app.webhooks.post(
        "agent.reply",
        summary="Evento agent.reply",
        description=DESCRICAO_WEBHOOK,
        tags=["webhooks"],
    )
    def agent_reply_webhook(
        body: AgentReply,
        x_saturday_timestamp: Annotated[
            str,
            Header(
                alias="X-Saturday-Timestamp",
                description="Segundos Unix usados no cálculo da assinatura.",
            ),
        ],
        x_saturday_signature: Annotated[
            str,
            Header(
                alias="X-Saturday-Signature",
                description=(
                    "sha256=<hex> do HMAC-SHA256 de '{timestamp}.' + corpo JSON, "
                    "com SATURDAY_WEBHOOK_SECRET."
                ),
            ),
        ],
    ) -> None:
        # A rota existe apenas para documentação; o webhook é enviado pelo
        # cliente HTTP do Saturday, não recebido por esta aplicação.
        _ = (body, x_saturday_timestamp, x_saturday_signature)
