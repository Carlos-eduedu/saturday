"""Respostas de dúvidas pelo LLM, sempre ancoradas na FAQ."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from saturday.faq import FAQ
from saturday.services.anexos import Anexo
from saturday.services.openrouter import OpenRouterClient, OpenRouterError
from saturday.settings import LLM_TEMPERATURE, LLM_TIMEOUT_S, Settings

logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Falha ao consultar o modelo de texto."""


@dataclass(frozen=True)
class LLMAnswer:
    resposta: str
    resolvido: bool


def _system_prompt(resumo: str | None) -> str:
    partes = [
        "Você é o assistente virtual da MEX, especializado em portabilidade de "
        "empréstimos consignados. Responda em português do Brasil, de forma curta "
        "e cordial.",
        "Use SOMENTE as informações da FAQ e do resumo abaixo. Não invente "
        "procedimentos, prazos, condições ou valores. O resumo já vem formatado: "
        "não calcule, não altere e não escreva números que não estejam nele.",
        "Se a resposta não estiver na FAQ nem no resumo, devolva "
        '{"resposta": "", "resolvido": false}.',
        "Devolva SOMENTE um objeto JSON, sem markdown, no formato "
        '{"resposta": "texto", "resolvido": true}.',
        "FAQ:\n" + FAQ,
    ]
    if resumo:
        partes.append("Resumo da análise de portabilidade:\n" + resumo)
    return "\n\n".join(partes)


def _extrair_json(content: str) -> dict[str, Any]:
    """Extrai o primeiro objeto JSON do texto, aceitando blocos markdown."""

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        inicio, fim = content.find("{"), content.rfind("}")
        if inicio < 0 or fim <= inicio:
            raise LLMError("modelo não devolveu JSON") from None
        try:
            data = json.loads(content[inicio : fim + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("modelo não devolveu JSON válido") from exc
    if not isinstance(data, dict):
        raise LLMError("modelo devolveu um JSON inesperado")
    return data


def _parse(content: str) -> LLMAnswer:
    data = _extrair_json(content)
    resposta = data.get("resposta")
    if not isinstance(resposta, str) or not resposta.strip():
        return LLMAnswer(resposta="", resolvido=False)

    resolvido_raw = data.get("resolvido", False)
    if isinstance(resolvido_raw, str):
        resolvido = resolvido_raw.strip().lower() in {"true", "sim", "1", "yes"}
    else:
        resolvido = bool(resolvido_raw)
    return LLMAnswer(resposta=resposta.strip(), resolvido=resolvido)


PROMPT_EXTRATO = """\
Você lê extratos de empréstimos consignados do Meu INSS (Hiscon).

Devolva SOMENTE um objeto JSON, com exatamente os campos abaixo:
{
  "ehHiscon": true,
  "especie": "32",
  "liberadoParaEmprestimo": true,
  "dataEmissao": "dd/mm/aaaa",
  "margemUtilizada": 0.00,
  "margemDisponivel": 0.00,
  "margemReservada": 0.00,
  "margemExtrapolada": 0.00,
  "contratos": [
    {
      "banco": "033 - SANTANDER",
      "situacao": "Ativo",
      "parcela": 0.00,
      "taxaMensal": 0.00,
      "qtdParcelas": 0,
      "inicioDesconto": "MM/AAAA",
      "dataInclusao": "dd/mm/aaaa"
    }
  ]
}

Regras:
- ehHiscon é false quando o documento não for o extrato de empréstimos do Meu INSS.
- Leia todas as páginas e todos os contratos.
- Use números com ponto decimal, sem separador de milhar (ex.: 1234.56).
- taxaMensal é a taxa mensal do contrato em % a.m., não o CET.
- Se um campo não estiver legível, use null. Nunca invente valores.
- NÃO transcreva nome, CPF, número do benefício, número de contrato, agência ou
  conta bancária. Não inclua campos além dos pedidos.
"""


def _parte_anexo(anexo: Anexo) -> dict[str, Any]:
    if anexo.mime_type == "application/pdf":
        return {
            "type": "file",
            "file": {
                "filename": "extrato.pdf",
                "file_data": anexo.data_url,
            },
        }
    return {"type": "image_url", "image_url": {"url": anexo.data_url}}


class LLMClient:
    """Cliente de texto e visão do OpenRouter."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._settings = settings
        self._openrouter = OpenRouterClient(
            http,
            settings.openrouter_api_key.get_secret_value(),
        )

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._openrouter.post_json(
            OPENROUTER_CHAT_URL,
            payload,
            LLM_TIMEOUT_S,
        )

    def ler_extrato(self, anexos: list[Anexo]) -> dict[str, Any]:
        """Lê todos os anexos numa única chamada ao modelo de visão."""

        if not anexos:
            raise LLMError("nenhum anexo")
        if not self._settings.openrouter_api_key.get_secret_value():
            raise LLMError("modelo de visão não configurado")
        if not self._settings.vision_model:
            raise LLMError("modelo de visão não configurado")

        conteudo: list[dict[str, Any]] = [{"type": "text", "text": PROMPT_EXTRATO}]
        conteudo.extend(_parte_anexo(anexo) for anexo in anexos)
        payload = {
            "model": self._settings.vision_model,
            "temperature": 0,
            "messages": [{"role": "user", "content": conteudo}],
            "response_format": {"type": "json_object"},
        }
        try:
            dados = self._post_json(payload)
            content = dados["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("leitura_extrato_falhou: %s", type(exc).__name__)
            raise LLMError("Falha ao ler o extrato") from exc

        if not isinstance(content, str):
            raise LLMError("modelo devolveu conteúdo vazio")
        return _extrair_json(content)

    def responder(
        self,
        historico: list[dict[str, str]],
        resumo: str | None = None,
    ) -> LLMAnswer:
        """Responde a dúvida do cliente. Levanta ``LLMError`` em qualquer falha."""

        if not self._settings.openrouter_api_key.get_secret_value():
            raise LLMError("LLM não configurado")
        if not self._settings.llm_model:
            raise LLMError("LLM não configurado")

        mensagens: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(resumo)}]
        mensagens.extend(historico)

        payload = {
            "model": self._settings.llm_model,
            "temperature": LLM_TEMPERATURE,
            "messages": mensagens,
            "response_format": {"type": "json_object"},
        }
        try:
            dados = self._post_json(payload)
            content = dados["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("llm_falhou: %s", type(exc).__name__)
            raise LLMError("Falha ao consultar o LLM") from exc

        if not isinstance(content, str):
            raise LLMError("LLM devolveu conteúdo vazio")
        return _parse(content)


__all__ = ["LLMAnswer", "LLMClient", "LLMError", "OpenRouterError"]
