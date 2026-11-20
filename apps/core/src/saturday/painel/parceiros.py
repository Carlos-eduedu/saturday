"""Parceiros que o Saturday chama, para a aba Integrações (só leitura).

Cada parceiro diz se está ligado, o host que chama e, por segredo, só se ele
está configurado: o valor nunca sai daqui (regra 8).
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import SecretStr

from saturday.fontes.brasilapi import BASE_URL as BRASILAPI_URL
from saturday.services.llm import OPENROUTER_CHAT_URL
from saturday.settings import Settings

Situacao = Literal["ligado", "desligado", "falta_chave"]


def _host(url: str) -> str:
    # `netloc` traria o `usuario:senha@` de uma URL com credencial.
    partes = urlparse(url)
    if not partes.hostname:
        return ""
    return f"{partes.hostname}:{partes.port}" if partes.port else partes.hostname


def _parceiro(
    id_: str,
    nome: str,
    descricao: str,
    *,
    ativo: bool,
    url: str,
    segredos: dict[str, SecretStr],
    sempre: bool = False,
    em_canais: bool = False,
) -> dict[str, Any]:
    configurados = {nome: bool(valor.get_secret_value()) for nome, valor in segredos.items()}
    situacao: Situacao = (
        "desligado" if not ativo else "ligado" if all(configurados.values()) else "falta_chave"
    )
    return {
        "id": id_,
        "nome": nome,
        "descricao": descricao,
        "situacao": situacao,
        "sempre": sempre,
        "host": _host(url),
        "segredos": configurados,
        "em_canais": em_canais,
    }


def parceiros(s: Settings) -> list[dict[str, Any]]:
    return [
        _parceiro(
            "meta",
            "Meta (WhatsApp)",
            "Cloud API do WhatsApp: recebe e envia as mensagens dos números oficiais.",
            ativo=bool(s.whatsapp_numeros),
            url=s.whatsapp_graph_url,
            segredos={"token": s.whatsapp_token, "app_secret": s.whatsapp_app_secret},
            em_canais=True,
        ),
        _parceiro(
            "evolution",
            "Evolution",
            "WhatsApp pelo QR: as instâncias que o gestor conecta em Canais.",
            ativo=s.evolution_ativo,
            url=s.evolution_url,
            segredos={
                "chave_api": s.evolution_api_key,
                "token_webhook": s.evolution_webhook_token,
            },
            em_canais=True,
        ),
        _parceiro(
            "granatech",
            "Granatech",
            "Crédito do Trabalhador (CLT): consulta, simulação e proposta.",
            ativo=s.granatech_ativo,
            url=s.granatech_base_url,
            segredos={
                "chave_api": s.granatech_chave_api,
                "token_webhook": s.granatech_webhook_token,
            },
        ),
        _parceiro(
            "c6",
            "C6",
            "INSS: simulação do contrato novo pela API do banco.",
            ativo=s.c6_ativo,
            url=s.c6_base_url,
            segredos={"senha": s.c6_senha},
        ),
        _parceiro(
            "icred",
            "iCred",
            "INSS: consulta pelo motor da MEX, com chave própria.",
            ativo=s.icred_ativo,
            url=s.icred_base_url,
            segredos={"chave_api": s.icred_chave_api, "segredo_webhook": s.icred_webhook_segredo},
        ),
        _parceiro(
            "brasilapi",
            "BrasilAPI",
            "Dados públicos de cadastro, como CEP e CNPJ.",
            ativo=True,
            url=BRASILAPI_URL,
            segredos={},
            sempre=True,
        ),
        _parceiro(
            "openrouter",
            "OpenRouter",
            "Modelos de IA: classificador, respostas da FAQ e leitura de anexos.",
            ativo=True,
            url=OPENROUTER_CHAT_URL,
            segredos={"chave_api": s.openrouter_api_key},
            sempre=True,
        ),
        _parceiro(
            "transcricao",
            "Transcrição de áudio",
            "Transforma em texto os áudios que o cliente manda.",
            ativo=bool(s.transcricao_modelo),
            url=s.transcricao_base_url,
            segredos={"chave_api": s.transcricao_api_key},
        ),
        _parceiro(
            "storage",
            "Storage (S3)",
            "Guarda mídia e documentos das conversas, em bucket privado.",
            ativo=bool(s.s3_bucket),
            url=s.s3_endpoint,
            segredos={"chave_acesso": s.s3_access_key, "chave_secreta": s.s3_secret_key},
        ),
    ]
