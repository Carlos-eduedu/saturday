"""Testes da leitura/normalização do extrato (etapa 4)."""

from __future__ import annotations

import base64
import json
import socket
from datetime import date

import httpx
import pytest

from saturday.portabilidade.hiscon import (
    STATUS_CONFERENCIA_FALHOU,
    STATUS_ESPECIE_NAO_ATENDIDA,
    STATUS_ILEGIVEL,
    STATUS_MES_ERRADO,
    STATUS_NAO_HISCON,
    STATUS_OK,
    conferir_margem,
    normalizar_extrato,
    numero_brasileiro,
    validar_extrato,
)
from saturday.services import anexos as anexos_service
from saturday.services.anexos import Anexo, AnexoInvalido, AnexosClient
from saturday.services.llm import LLMClient
from saturday.settings import Settings

HOJE = date(2026, 10, 8)


def json_extrato(**extras) -> dict:
    dados = {
        "ehHiscon": True,
        "especie": "32",
        "liberadoParaEmprestimo": True,
        "dataEmissao": "08/10/2026",
        "margemUtilizada": 100.0,
        "margemDisponivel": 90.0,
        "margemReservada": 0.0,
        "margemExtrapolada": 0.0,
        "contratos": [
            {
                "banco": "33 - SANTANDER",
                "situacao": "Ativo",
                "parcela": 100.0,
                "taxaMensal": "1,85",
                "qtdParcelas": 84,
                "inicioDesconto": "1/2023",
                "dataInclusao": "01/01/2020",
            }
        ],
    }
    dados.update(extras)
    return dados


def test_extrato_valido_do_mes_corrente_passa():
    extrato = normalizar_extrato(json_extrato())

    assert validar_extrato(extrato, HOJE) == STATUS_OK
    assert conferir_margem(extrato) is True
    c = extrato.contratos[0]
    assert c.banco == "033 - SANTANDER"
    assert c.banco_codigo == "033"
    assert c.taxaMensal == 1.85
    assert c.inicioDesconto == "01/2023"
    assert c.legivel is True


def test_conferencia_divergente_em_um_e_meio_falha():
    extrato = normalizar_extrato(json_extrato(margemUtilizada=101.50))
    assert validar_extrato(extrato, HOJE) == STATUS_CONFERENCIA_FALHOU


def test_conferencia_com_tolerancia_de_um_real_passa():
    extrato = normalizar_extrato(json_extrato(margemUtilizada=101.00))
    assert validar_extrato(extrato, HOJE) == STATUS_OK


def test_extrato_do_mes_anterior_pede_novo():
    extrato = normalizar_extrato(json_extrato(dataEmissao="08/09/2026"))
    assert validar_extrato(extrato, HOJE) == STATUS_MES_ERRADO


def test_eh_hiscon_false_pede_extrato_correto():
    extrato = normalizar_extrato(json_extrato(ehHiscon=False))
    assert validar_extrato(extrato, HOJE) == STATUS_NAO_HISCON


def test_data_de_emissao_ilegivel():
    extrato = normalizar_extrato(json_extrato(dataEmissao="31/02/2026"))
    assert validar_extrato(extrato, HOJE) == STATUS_ILEGIVEL


def test_contrato_com_taxa_zero_e_ilegivel_sem_travar_os_outros():
    dados = json_extrato(
        margemUtilizada=600.0,
        contratos=[
            {
                "banco": "033 - SANTANDER",
                "situacao": "Ativo",
                "parcela": 100.0,
                "taxaMensal": 0,
                "qtdParcelas": 84,
                "inicioDesconto": "01/2023",
                "dataInclusao": "01/01/2020",
            },
            {
                "banco": "643 - PINE",
                "situacao": "Ativo",
                "parcela": 500.0,
                "taxaMensal": 1.66,
                "qtdParcelas": 84,
                "inicioDesconto": "01/2024",
                "dataInclusao": "01/01/2020",
            },
        ],
    )
    extrato = normalizar_extrato(dados)

    assert extrato.contratos[0].legivel is False
    assert extrato.contratos[1].legivel is True
    assert validar_extrato(extrato, HOJE) == STATUS_OK


def test_numero_brasileiro():
    assert numero_brasileiro("1.234,56") == 1234.56
    assert numero_brasileiro("R$ 1.234,56") == 1234.56
    assert numero_brasileiro("abc") is None
    assert numero_brasileiro(None) is None
    assert numero_brasileiro("0") == 0.0


def test_especie_87_nao_atendida():
    extrato = normalizar_extrato(json_extrato(especie="87"))
    assert validar_extrato(extrato, HOJE) == STATUS_ESPECIE_NAO_ATENDIDA


def test_soma_apenas_contratos_ativos():
    dados = json_extrato(
        margemUtilizada=100.0,
        contratos=[
            {
                "banco": "033 - SANTANDER",
                "situacao": "Ativo",
                "parcela": 60.0,
                "taxaMensal": 1.85,
                "qtdParcelas": 84,
                "inicioDesconto": "01/2023",
                "dataInclusao": "01/01/2020",
            },
            {
                "banco": "643 - PINE",
                "situacao": "Suspenso INSS",
                "parcela": 500.0,
                "taxaMensal": 1.66,
                "qtdParcelas": 84,
                "inicioDesconto": "01/2024",
                "dataInclusao": "01/01/2020",
            },
        ],
    )
    extrato = normalizar_extrato(dados)
    assert conferir_margem(extrato) is False  # 60 != 100

    extrato = normalizar_extrato({**dados, "margemUtilizada": 60.0})
    assert conferir_margem(extrato) is True


def _settings(**extras) -> Settings:
    return Settings(environment="pytest", **extras)


def _sem_rede(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"chamada inesperada: {request.method} {request.url}")


def test_anexo_base64():
    conteudo = b"%PDF-1.7 teste"
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(),
    )
    anexo = avec.carregar_anexo(
        {
            "base64": base64.b64encode(conteudo).decode(),
            "mime_type": "application/pdf",
        }
    )
    assert anexo.data == conteudo
    assert anexo.data_url.startswith("data:application/pdf;base64,")


def test_anexo_mime_invalido():
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(),
    )
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo({"base64": base64.b64encode(b"x").decode(), "mime_type": "text/plain"})


def test_anexo_base64_invalido():
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(),
    )
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo({"base64": "***", "mime_type": "image/jpeg"})


def test_anexo_acima_do_limite():
    avec = AnexosClient(
        httpx.Client(transport=httpx.MockTransport(_sem_rede)),
        _settings(),
    )
    grande = b"x" * (anexos_service.LIMITE_BYTES + 1)
    with pytest.raises(AnexoInvalido):
        avec.carregar_anexo(
            {
                "base64": base64.b64encode(grande).decode(),
                "mime_type": "image/png",
            }
        )


def test_anexo_url_baixa_e_valida(monkeypatch):
    chamadas: dict = {}

    monkeypatch.setattr(
        anexos_service.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas["url"] = str(request.url)
        chamadas["metodo"] = request.method
        return httpx.Response(200, content=b"imagem")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        avec = AnexosClient(http, _settings(anexo_dominios=["arquivo.test"]))
        anexo = avec.carregar_anexo(
            {"url": "https://arquivo.test/extrato.jpg", "mime_type": "image/jpeg"}
        )

    assert anexo.data == b"imagem"
    assert chamadas == {
        "url": "https://arquivo.test/extrato.jpg",
        "metodo": "GET",
    }


def test_ler_extrato_manda_todos_anexos_numa_chamada():
    capturado: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(json_extrato())}}]},
        )

    settings = _settings(
        openrouter_api_key="chave",
        vision_model="modelo-visao",
    )
    anexos = [
        Anexo(mime_type="application/pdf", data=b"pdf"),
        Anexo(mime_type="image/jpeg", data=b"foto"),
    ]

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        dados = LLMClient(http, settings).ler_extrato(anexos)

    assert dados["ehHiscon"] is True
    assert capturado["model"] == "modelo-visao"
    conteudo = capturado["messages"][0]["content"]
    tipos = [parte["type"] for parte in conteudo if parte["type"] != "text"]
    assert tipos == ["file", "image_url"]

    extrato = normalizar_extrato(dados)
    assert validar_extrato(extrato, HOJE) == STATUS_OK
