"""Integração do APP MEX (decisão 0035), fase 2: aviso de status por webhook.

Postgres real; o evento da Granatech entra por `jobs.granatech.aplicar` e sai
pelo outbox com o `EntregadorIntegracao`, contra um endereço de mentira.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from conftest import entrar_como
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Alerta, ConsultaGranatech, Integracao, Outbox, PropostaGranatech
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as jobs
from saturday.jobs.outbox import EntregadorIntegracao, drenar
from saturday.settings import Settings

PAINEL = "/admin/gestao/integracoes"
CPF = "52998224725"
URL = "https://app.mex.test/avisos"


def _integracao(fabrica: sessionmaker[Session], **extras: Any) -> uuid.UUID:
    with abrir_sessao(fabrica) as sessao:
        campos: dict[str, Any] = {"webhook_url": URL, "webhook_segredo": "whsec_teste", **extras}
        linha = Integracao(
            nome="APP MEX", token_hash=uuid.uuid4().hex, escopos=["leitura"], **campos
        )
        sessao.add(linha)
        sessao.flush()
        return linha.id


def _consulta(fabrica: sessionmaker[Session], integracao_id: uuid.UUID | None) -> None:
    with abrir_sessao(fabrica) as sessao:
        sessao.add(
            ConsultaGranatech(
                id_externo="c-1", cpf=CPF, status="PENDING", integracao_id=integracao_id
            )
        )


def _evento_consulta(fabrica: sessionmaker[Session], status: str) -> None:
    payload = {"tipo": "consulta", "id_consulta": "c-1", "status": status, "cpf": CPF}
    jobs.aplicar(fabrica, None, payload)


def _avisos(fabrica: sessionmaker[Session]) -> list[Outbox]:
    with abrir_sessao(fabrica) as sessao:
        linhas = list(sessao.scalars(select(Outbox).order_by(Outbox.id)).all())
        sessao.expunge_all()
        return linhas


def _recebidos(respostas: list[int]) -> tuple[httpx.Client, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(respostas.pop(0) if respostas else 200)

    return httpx.Client(transport=httpx.MockTransport(responder)), pedidos


def _drenar(fabrica: sessionmaker[Session], settings: Settings, http: httpx.Client) -> None:
    drenar(fabrica, EntregadorIntegracao(http, fabrica), settings)
    # O reagendamento põe a próxima tentativa no futuro; o teste a traz para agora.
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(update(Outbox).values(proxima_tentativa_em=Outbox.criada_em))


# ------------------------------------------------------------------ enfileirar


def test_status_novo_de_item_da_integracao_vira_aviso(fabrica: Any) -> None:
    _consulta(fabrica, _integracao(fabrica))
    _evento_consulta(fabrica, "PROCESSING")

    (aviso,) = _avisos(fabrica)
    assert aviso.canal == "integracao" and aviso.conversa_id is None
    assert aviso.payload["tipo"] == "consulta"
    # O evento sai como chegou, menos o CPF.
    assert aviso.payload["evento"] == {
        "tipo": "consulta",
        "id_consulta": "c-1",
        "status": "PROCESSING",
        "cpf": "***.***.***-25",
    }


def test_status_repetido_ou_regressao_nao_avisa(fabrica: Any) -> None:
    _consulta(fabrica, _integracao(fabrica))
    _evento_consulta(fabrica, "PROCESSING")
    _evento_consulta(fabrica, "PROCESSING")
    _evento_consulta(fabrica, "PENDING")
    assert len(_avisos(fabrica)) == 1


def test_item_do_agente_nao_avisa(fabrica: Any) -> None:
    _integracao(fabrica)
    _consulta(fabrica, None)
    _evento_consulta(fabrica, "PROCESSING")
    assert _avisos(fabrica) == []


def test_integracao_sem_webhook_nao_avisa(fabrica: Any) -> None:
    _consulta(fabrica, _integracao(fabrica, webhook_url=None))
    _evento_consulta(fabrica, "PROCESSING")
    assert _avisos(fabrica) == []


def test_proposta_da_integracao_tambem_avisa(fabrica: Any) -> None:
    integracao_id = _integracao(fabrica)
    _consulta(fabrica, integracao_id)
    with abrir_sessao(fabrica) as sessao:
        consulta_id = sessao.scalars(select(ConsultaGranatech.id)).one()
        sessao.add(
            PropostaGranatech(
                consulta_id=consulta_id,
                id_externo="p-1",
                valor_parcela=Decimal("300.00"),
                numero_parcelas=36,
                integracao_id=integracao_id,
            )
        )
    jobs.aplicar(
        fabrica,
        None,
        {
            "tipo": "proposta",
            "id_proposta": "p-1",
            "status": "PENDING_FORMALIZATION",
            "tipo_notificacao": "AGUARDANDO_FORMALIZACAO",
        },
    )
    (aviso,) = _avisos(fabrica)
    assert aviso.payload["tipo"] == "proposta"
    assert aviso.payload["evento"]["status"] == "PENDING_FORMALIZATION"


# ------------------------------------------------------------------ entregar


def test_aviso_sai_assinado(fabrica: Any, settings: Settings) -> None:
    _consulta(fabrica, _integracao(fabrica))
    _evento_consulta(fabrica, "PROCESSING")
    http, pedidos = _recebidos([200])

    _drenar(fabrica, settings, http)

    (pedido,) = pedidos
    assert str(pedido.url) == URL
    corpo = pedido.content
    esperada = hmac.new(
        b"whsec_teste",
        pedido.headers["X-Saturday-Timestamp"].encode() + b"." + corpo,
        hashlib.sha256,
    ).hexdigest()
    assert pedido.headers["X-Saturday-Signature"] == f"sha256={esperada}"
    assert json.loads(corpo)["evento"]["status"] == "PROCESSING"
    assert _avisos(fabrica)[0].entregue_em is not None


def test_falha_reagenda_e_desistencia_vira_alerta(fabrica: Any, settings: Settings) -> None:
    _consulta(fabrica, _integracao(fabrica))
    _evento_consulta(fabrica, "PROCESSING")
    http, pedidos = _recebidos([500] * 50)

    for _ in range(settings.outbox_max_tentativas):
        _drenar(fabrica, settings, http)

    assert len(pedidos) == settings.outbox_max_tentativas
    assert _avisos(fabrica)[0].falhou_em is not None
    with abrir_sessao(fabrica) as sessao:
        (alerta,) = sessao.scalars(select(Alerta)).all()
        assert alerta.tipo == "integracao_webhook_falhou"
        assert alerta.conversa_id is None


def test_integracao_revogada_desiste_sem_chamar(fabrica: Any, settings: Settings) -> None:
    _consulta(fabrica, _integracao(fabrica))
    _evento_consulta(fabrica, "PROCESSING")
    # Revogada depois do aviso entrar na fila.
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(update(Integracao).values(revogada_em=func.now()))
    http, pedidos = _recebidos([])

    _drenar(fabrica, settings, http)

    assert pedidos == []
    assert _avisos(fabrica)[0].falhou_em is not None


# ------------------------------------------------------------------ painel


def test_painel_cadastra_endereco_e_segredo(client_pg: TestClient, fabrica: Any) -> None:
    csrf = entrar_como(client_pg, fabrica, "gestor")
    criada = client_pg.post(PAINEL, json={"nome": "APP MEX", "escopos": ["leitura"]}, headers=csrf)
    integracao_id = criada.json()["id"]
    rota = f"{PAINEL}/{integracao_id}/webhook"

    assert client_pg.put(rota, json={"url": "ftp://x"}, headers=csrf).status_code == 422
    assert client_pg.put(rota, json={"url": URL}, headers=csrf).status_code == 204
    segredo = client_pg.post(f"{rota}/segredo", headers=csrf).json()["segredo"]
    assert segredo.startswith("whsec_")

    (linha,) = client_pg.get(PAINEL).json()
    assert linha["webhook_url"] == URL and linha["tem_segredo"] is True
    assert "segredo" not in json.dumps(linha).replace("tem_segredo", "")
    assert client_pg.get(f"{rota}/entregas").json() == []

    csrf = entrar_como(client_pg, fabrica, "atendente")
    assert client_pg.put(rota, json={"url": URL}, headers=csrf).status_code == 403


def test_painel_lista_as_entregas(client_pg: TestClient, fabrica: Any, settings: Settings) -> None:
    integracao_id = _integracao(fabrica)
    _consulta(fabrica, integracao_id)
    _evento_consulta(fabrica, "PROCESSING")
    entrar_como(client_pg, fabrica, "gestor")
    (entrega,) = client_pg.get(f"{PAINEL}/{integracao_id}/webhook/entregas").json()
    assert entrega["tipo"] == "consulta"
    assert entrega["status"] == "PROCESSING"
    assert entrega["situacao"] == "pendente"


pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")
