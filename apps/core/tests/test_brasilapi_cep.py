"""Busca de endereço por CEP na BrasilAPI (decisão 0034), sem rede."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import ChamadaExterna
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.fontes.brasilapi import BrasilAPI


def _api(fabrica: sessionmaker[Session], resposta: httpx.Response) -> BrasilAPI:
    http = httpx.Client(transport=httpx.MockTransport(lambda _pedido: resposta))
    return BrasilAPI(http, fabrica, dormir=lambda _s: None)


def test_cep_encontrado(fabrica: sessionmaker[Session]) -> None:
    corpo = {
        "cep": "01310100",
        "state": "sp",
        "city": "São Paulo",
        "neighborhood": "Bela Vista",
        "street": "Avenida Paulista",
    }
    api = _api(fabrica, httpx.Response(200, json=corpo))

    assert api.buscar_cep("01310100") == {
        "logradouro": "Avenida Paulista",
        "bairro": "Bela Vista",
        "cidade": "São Paulo",
        "uf": "SP",
    }
    with abrir_sessao(fabrica) as sessao:
        rota = sessao.scalars(select(ChamadaExterna.rota)).one()
    # Só a rota com o marcador: o CEP do cliente não vai para o registro.
    assert rota == "/api/cep/v1/{cep}"


def test_cep_nao_encontrado(fabrica: sessionmaker[Session]) -> None:
    api = _api(fabrica, httpx.Response(404, json={"message": "não encontrado"}))
    assert api.buscar_cep("99999999") is None
