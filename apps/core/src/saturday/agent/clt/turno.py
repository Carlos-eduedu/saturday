"""Turno do ramo CLT: o estado da jornada e as saídas que toda etapa usa."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage

from saturday.agent.clt import leitura
from saturday.agent.clt.mensagens import texto
from saturday.agent.context import AgentContext
from saturday.agent.state import AgentState
from saturday.bancos.granatech.cliente import ClienteGranatech

logger = logging.getLogger("saturday.agent.clt.nos")

PERGUNTAS = {
    "carteira": "triagem_carteira",
    "tempo_casa": "triagem_tempo_casa",
    "contrato_especial": "triagem_contrato_especial",
    "granatech": "triagem_granatech",
    "funcionarios": "triagem_funcionarios",
    "cnpj": "pedir_cnpj",
    "cpf": "pedir_cpf",
    "nome": "pedir_nome",
    "nascimento": "pedir_nascimento",
    "sexo": "pedir_sexo",
    "email": "pedir_email",
    "celular": "pedir_celular",
    "sim": "consentimento",
    "vinculo": "escolher_vinculo",
    "mae": "confirmar_mae",
    "endereco": "confirmar_endereco",
    "estado_civil": "pedir_estado_civil",
    "banco": "pedir_banco",
    "tipo_conta": "pedir_tipo_conta",
    "agencia": "pedir_agencia",
    "conta": "pedir_conta",
    "titular": "confirmar_titular",
}
ERROS_ATE_HANDOFF = 2


# ---------------------------------------------------------------- formatação


def reais(valor: Decimal) -> str:
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def primeiro_nome(nome: str) -> str:
    return nome.split()[0].capitalize() if nome.strip() else ""


# ---------------------------------------------------------------- turno


@dataclass
class Turno:
    """O que uma etapa precisa: estado da jornada, texto e clientes."""

    clt: dict[str, Any]
    state: AgentState
    contexto: AgentContext
    texto: str
    hoje: date
    # Opt-in ou opt-out de marketing decidido neste turno (o serviço grava).
    marketing: str | None = None

    @property
    def dados(self) -> dict[str, Any]:
        dados: dict[str, Any] = self.clt.setdefault("dados", {})
        return dados

    @property
    def granatech(self) -> ClienteGranatech:
        if self.contexto.granatech is None:
            raise RuntimeError("ramo CLT sem cliente da Granatech")
        return self.contexto.granatech

    @property
    def conversa_id(self) -> uuid.UUID | None:
        ref = self.state.get("conversa_ref")
        return uuid.UUID(ref) if ref else None

    # -- saídas -------------------------------------------------------

    def responder(self, *partes: str) -> dict[str, Any]:
        resposta = "\n\n".join(p for p in partes if p)
        return {
            "marketing": self.marketing,
            "clt": self.clt,
            "status": "answered",
            "answer": resposta,
            "needs_human": False,
            "messages": [AIMessage(content=resposta)] if resposta else [],
        }

    def perguntar(self, etapa: str, passo: str, *antes: str, **valores: object) -> dict[str, Any]:
        self.clt.update(etapa=etapa, passo=passo, erros=0)
        return self.responder(*antes, texto(PERGUNTAS[passo], **valores))

    def handoff(
        self,
        motivo: str,
        resposta: str | None = None,
        *,
        detalhe: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Passa a conversa para um humano; ``detalhe`` vai para o alerta."""

        logger.info("clt_handoff etapa=%s motivo=%s", self.clt.get("etapa"), motivo)
        return {
            "clt": self.clt,
            "needs_human": True,
            "handoff_reason": motivo,
            "answer": resposta or texto("handoff"),
            "handoff_detalhe": detalhe,
        }

    def faq(self) -> dict[str, Any]:
        return {"clt": self.clt, "clt_faq": True}

    def nao_elegivel(self, chave: str, **valores: object) -> dict[str, Any]:
        logger.info("clt_nao_elegivel etapa=%s motivo=%s", self.clt.get("etapa"), chave)
        self.clt.update(etapa="nao_elegivel", passo=None, motivo=chave)
        return self.responder(texto(chave, **valores))

    def erro(self, chave: str, **valores: object) -> dict[str, Any]:
        """Resposta não reconhecida: pergunta vai à FAQ; dois erros, handoff."""

        if leitura.eh_pergunta(self.texto):
            return self.faq()
        if self.state.get("publico") == "inss":
            return self.handoff("mudou_publico")
        self.clt["erros"] = int(self.clt.get("erros") or 0) + 1
        if self.clt["erros"] >= ERROS_ATE_HANDOFF:
            return self.handoff("dado_invalido_repetido")
        return self.responder(texto(chave, **valores))
