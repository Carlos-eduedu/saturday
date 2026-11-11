"""Cliente Granatech contra o simulador (em processo) e Postgres."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import ModuleType
from typing import Any

import httpx
import pytest
from conftest import settings_granatech
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.bancos.granatech.cliente import ClienteGranatech, ErroGranatech, ErroIncerto
from saturday.dados.cota import CotaEsgotada
from saturday.dados.modelos import (
    Alerta,
    ChamadaExterna,
    ConsultaGranatech,
    Cota,
    PropostaGranatech,
)

CPF = "00189004967"

# O cliente passa o timeout por requisição; o TestClient ignora e avisa.
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")


class Relogio:
    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def esperas() -> list[float]:
    return []


def _cliente(
    http: httpx.Client,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
    **extras: Any,
) -> ClienteGranatech:
    return ClienteGranatech(
        http,
        settings_granatech(**extras),
        fabrica,
        relogio=relogio,
        dormir=esperas.append,
    )


@pytest.fixture
def cliente(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> ClienteGranatech:
    return _cliente(http_granatech, fabrica, relogio, esperas)


def _falha(sim: ModuleType, **falha: Any) -> None:
    sim.FALHAS.append(falha)


# ------------------------------------------------------------------ token e retry


def test_token_fica_em_cache(cliente: ClienteGranatech, simulador_granatech: ModuleType) -> None:
    cliente.bancos()
    cliente.bancos()

    assert len(simulador_granatech.LOGINS) == 1


def test_token_perto_de_vencer_e_renovado(
    cliente: ClienteGranatech, simulador_granatech: ModuleType, relogio: Relogio
) -> None:
    cliente.bancos()
    relogio.agora += 3600 - 299  # menos de 5 min para vencer

    cliente.bancos()

    assert len(simulador_granatech.LOGINS) == 2


def test_401_renova_e_repete_uma_vez(
    cliente: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    cliente.bancos()
    _falha(simulador_granatech, rota="/bancos", status=401)

    assert cliente.bancos()

    assert len(simulador_granatech.LOGINS) == 2


def test_401_seguido_nao_entra_em_laco(
    cliente: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    _falha(simulador_granatech, rota="/bancos", status=401, vezes=2)

    with pytest.raises(ErroGranatech) as erro:
        cliente.bancos()

    assert erro.value.status == 401


def test_get_com_500_repete_uma_vez(
    cliente: ClienteGranatech, simulador_granatech: ModuleType, esperas: list[float]
) -> None:
    _falha(simulador_granatech, rota="/bancos", status=500)

    assert cliente.bancos()

    assert esperas == [1.5]


def test_get_com_dois_500_desiste(
    cliente: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    _falha(simulador_granatech, rota="/bancos", status=500, vezes=2)

    with pytest.raises(ErroGranatech):
        cliente.bancos()


def test_post_com_500_e_incerto_e_nao_repete(
    cliente: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    _falha(simulador_granatech, rota="/termo-consentimento", status=500)

    with pytest.raises(ErroIncerto):
        cliente.assinar_termo(
            id_consulta=aberta.id_externo,
            cpf=CPF,
            email="a@b.com",
            nome="FULANO",
            telefone="11987654321",
        )

    termos = [c for c in simulador_granatech.CHAMADAS if c[1].endswith("/termo-consentimento")]
    assert len(termos) == 1


def test_timeout_no_get_repete_e_no_post_e_incerto(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _cliente(http_granatech, fabrica, relogio, esperas)
    cliente.bancos()  # token em cache
    original = http_granatech.request
    estouros = {"restantes": 1}

    def com_timeout(metodo: str, url: str, **kwargs: Any) -> httpx.Response:
        if estouros["restantes"] > 0:
            estouros["restantes"] -= 1
            raise httpx.ReadTimeout("simulado")
        return original(metodo, url, **kwargs)

    monkeypatch.setattr(http_granatech, "request", com_timeout)

    assert cliente.bancos()
    assert esperas == [1.5]

    estouros["restantes"] = 1
    with pytest.raises(ErroIncerto):
        cliente.assinar_termo(
            id_consulta="x", cpf=CPF, email="a@b.com", nome="F", telefone="11987654321"
        )


def test_chamadas_externas_guardam_so_a_rota_modelo(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO DE TAL", "11987654321")
    cliente.detalhe(aberta.id_externo)

    with fabrica() as sessao:
        rotas = sessao.scalars(select(ChamadaExterna.rota)).all()
    assert "/api-consignado/v1/consulta-saldo" in rotas
    assert "/api-consignado/v1/consulta-saldo/{id}" in rotas
    texto = " ".join(rotas)
    assert CPF not in texto
    assert "FULANO" not in texto
    assert aberta.id_externo not in texto


# ------------------------------------------------------------------ consulta e cota


def test_consulta_gasta_cota_e_fica_gravada(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    assert not aberta.reaproveitada
    assert aberta.status == "AWAITING_CLIENT_AUTHORIZATION"
    assert aberta.link_termo
    with fabrica() as sessao:
        assert sessao.scalar(select(func.sum(Cota.usadas))) == 1
        assert sessao.scalar(select(func.count(ConsultaGranatech.id))) == 1


def test_mesmo_cpf_reaproveita_a_consulta_local(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    primeira = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    segunda = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    assert segunda.reaproveitada
    assert segunda.id_externo == primeira.id_externo
    assert len(simulador_granatech.CONSULTAS) == 1
    with fabrica() as sessao:
        assert sessao.scalar(select(func.sum(Cota.usadas))) == 1


def test_consulta_que_so_existe_na_granatech_e_reaproveitada(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    simulador_granatech.CONSULTAS["remota-1"] = {
        "cpf": CPF,
        "status": "SUCCESS",
        "criada_em": date.today().isoformat(),
        "pronta_em": 0,
    }

    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    assert aberta.reaproveitada
    assert aberta.id_externo == "remota-1"
    with fabrica() as sessao:
        assert sessao.scalar(select(func.sum(Cota.usadas))) is None


def test_consulta_com_erro_nao_e_reaproveitada(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    primeira = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    with fabrica.begin() as sessao:
        sessao.get_one(ConsultaGranatech, primeira.id_local).status = "UNEXPECTED_ERROR"
    simulador_granatech.CONSULTAS[primeira.id_externo]["status"] = "UNEXPECTED_ERROR"

    segunda = cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    assert not segunda.reaproveitada
    assert segunda.id_externo != primeira.id_externo


def test_cota_diaria_esgotada_nao_chama_a_granatech(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
    simulador_granatech: ModuleType,
) -> None:
    cliente = _cliente(http_granatech, fabrica, relogio, esperas, granatech_cota_diaria=1)
    cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    with pytest.raises(CotaEsgotada) as erro:
        cliente.abrir_consulta("52998224725", "CICLANO", "11987654321")

    assert erro.value.motivo == "diaria"
    assert len(simulador_granatech.CONSULTAS) == 1


def test_cota_mensal_esgotada(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> None:
    cliente = _cliente(http_granatech, fabrica, relogio, esperas, granatech_cota_mensal=0)

    with pytest.raises(CotaEsgotada) as erro:
        cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    assert erro.value.motivo == "mensal"


def test_alerta_quando_passa_de_80_por_cento_do_mes(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> None:
    cliente = _cliente(http_granatech, fabrica, relogio, esperas, granatech_cota_mensal=5)
    for cpf in ("52998224725", "11144477735", "39053344705"):
        cliente.abrir_consulta(cpf, "FULANO", "11987654321")
    with fabrica() as sessao:
        assert sessao.scalar(select(func.count(Alerta.id))) == 0

    cliente.abrir_consulta(CPF, "FULANO", "11987654321")  # 4 de 5 = 80%
    cliente.abrir_consulta("16899535009", "FULANO", "11987654321")

    with fabrica() as sessao:
        tipos = sessao.scalars(select(Alerta.tipo)).all()
    assert tipos == ["cota_80"]


def test_400_comprovado_devolve_a_cota(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    with pytest.raises(ErroGranatech) as erro:
        cliente.abrir_consulta(CPF, "FULANO", "119876")  # telefone curto

    assert erro.value.status == 400
    with fabrica() as sessao:
        assert sessao.scalar(select(func.sum(Cota.usadas))) == 0


def test_erro_incerto_nao_devolve_a_cota(
    cliente: ClienteGranatech, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    _falha(simulador_granatech, rota="/consulta-saldo", status=500, vezes=2)

    with pytest.raises(ErroGranatech):
        cliente.abrir_consulta(CPF, "FULANO", "11987654321")

    with fabrica() as sessao:
        assert sessao.scalar(select(func.sum(Cota.usadas))) == 1


def test_detalhe_pronto_depois_do_termo(cliente: ClienteGranatech) -> None:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    antes, _ = cliente.detalhe(aberta.id_externo)
    cliente.assinar_termo(
        id_consulta=aberta.id_externo,
        cpf=CPF,
        email="a@b.com",
        nome="FULANO",
        telefone="11987654321",
    )

    depois, recorte = cliente.detalhe(aberta.id_externo)

    assert antes is None
    assert depois is not None
    assert [v.nome_empregador for v in depois.vinculos] == [
        "Prime Tech LTDA",
        "EMPREGADOR MOCK LTDA",
    ]
    assert [p.id for p in depois.vinculos[0].produtos] == ["AA17", "AA25", "AAA36", "AAA48"]
    assert recorte["pessoa_natural"]["document"] == CPF


# ------------------------------------------------------------------ simulação e teto


def _pedido(**extras: Any) -> dict[str, Any]:
    pedido: dict[str, Any] = {
        "id_produto": "AAA36",
        "id_margem": "margem-1",
        "numero_parcelas": 36,
        "idade": 36,
        "valor_parcela": Decimal("300"),
    }
    pedido.update(extras)
    return pedido


def test_simulacao_da_dev(cliente: ClienteGranatech) -> None:
    simulacao = cliente.simular(**_pedido(seguro=False))

    assert simulacao.liberado == Decimal("4619.53")
    assert simulacao.valor_iof == Decimal("175.28")
    assert simulacao.valor_seguro == Decimal("503.32")
    assert simulacao.valor_total_financiado == Decimal("5298.13")
    # Pediu sem seguro, mas a dev devolve só o bloco com seguro.
    assert simulacao.seguro_aplicado


def test_simulacao_abaixo_do_teto_nao_e_limitada(cliente: ClienteGranatech) -> None:
    simulacao = cliente.simular_no_teto(**_pedido())

    assert simulacao is not None
    assert not simulacao.limitado_ao_teto


def test_liberado_acima_do_teto_e_ajustado(
    cliente: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    simulacao = cliente.simular_no_teto(
        **_pedido(id_produto="AAA48", numero_parcelas=48, valor_parcela=Decimal("500"))
    )

    assert simulacao is not None
    assert simulacao.limitado_ao_teto
    assert simulacao.liberado <= Decimal("6999")
    assert simulacao.valor_parcela < Decimal("500")
    simulacoes = [c for c in simulador_granatech.CHAMADAS if "/simulacao/" in c[1]]
    assert 2 <= len(simulacoes) <= 5


def test_teto_baixo_demais_fica_sem_oferta(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> None:
    cliente = _cliente(
        http_granatech, fabrica, relogio, esperas, granatech_teto_liberado=Decimal("500")
    )

    assert cliente.simular_no_teto(**_pedido()) is None


# ------------------------------------------------------------------ proposta


def _consulta_pronta(cliente: ClienteGranatech) -> tuple[int, str]:
    aberta = cliente.abrir_consulta(CPF, "FULANO", "11987654321")
    return aberta.id_local, aberta.id_externo


def _corpo(id_consulta: str) -> dict[str, Any]:
    return {
        "id_consulta": id_consulta,
        "id_produto": "AAA36",
        "id_margem": "margem-1",
        "informacoesFinanceira": [{"valor_parcela": 300.0, "numero_parcelas": 36}],
    }


@pytest.fixture
def cliente_proposta(
    http_granatech: TestClient,
    fabrica: sessionmaker[Session],
    relogio: Relogio,
    esperas: list[float],
) -> ClienteGranatech:
    return _cliente(http_granatech, fabrica, relogio, esperas, granatech_proposta_ativa=True)


def test_proposta_desligada_por_flag(cliente: ClienteGranatech) -> None:
    with pytest.raises(RuntimeError, match="PROPOSTA_ATIVA"):
        cliente.criar_proposta(consulta_id=1, corpo=_corpo("x"))


def test_proposta_criada_uma_vez(
    cliente_proposta: ClienteGranatech, simulador_granatech: ModuleType
) -> None:
    consulta_id, id_consulta = _consulta_pronta(cliente_proposta)

    primeira = cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo(id_consulta))
    segunda = cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo(id_consulta))

    assert primeira == segunda
    assert len(simulador_granatech.PROPOSTAS) == 1


@pytest.mark.parametrize("falha", [500, "timeout"])
def test_post_incerto_reconcilia_pela_listagem_sem_novo_post(
    cliente_proposta: ClienteGranatech,
    simulador_granatech: ModuleType,
    fabrica: sessionmaker[Session],
    falha: object,
) -> None:
    consulta_id, id_consulta = _consulta_pronta(cliente_proposta)
    simulador_granatech.CONFIG["timeout_s"] = 0
    # A Granatech cria, mas a resposta se perde.
    _falha(simulador_granatech, rota="/propostas", metodo="POST", status=falha, registrar=True)

    id_externo = cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo(id_consulta))

    assert list(simulador_granatech.PROPOSTAS) == [id_externo]
    posts = [
        c for c in simulador_granatech.CHAMADAS if c == ("POST", "/api-consignado/v1/propostas")
    ]
    assert len(posts) == 1
    with fabrica() as sessao:
        proposta = sessao.scalars(select(PropostaGranatech)).one()
    assert proposta.estado_envio == "criada"
    assert proposta.id_externo == id_externo


def test_post_incerto_sem_proposta_na_listagem_nao_tenta_de_novo(
    cliente_proposta: ClienteGranatech,
    simulador_granatech: ModuleType,
    fabrica: sessionmaker[Session],
) -> None:
    consulta_id, id_consulta = _consulta_pronta(cliente_proposta)
    # Falhou antes de criar: a listagem não tem nada.
    _falha(simulador_granatech, rota="/propostas", metodo="POST", status=500)

    with pytest.raises(ErroIncerto):
        cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo(id_consulta))
    # Uma segunda chamada também só procura: nenhum POST novo.
    with pytest.raises(ErroIncerto):
        cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo(id_consulta))

    posts = [
        c for c in simulador_granatech.CHAMADAS if c == ("POST", "/api-consignado/v1/propostas")
    ]
    assert len(posts) == 1
    assert simulador_granatech.PROPOSTAS == {}
    with fabrica() as sessao:
        assert sessao.scalars(select(PropostaGranatech.estado_envio)).one() == "incerta"


def test_post_recusado_marca_falhou(
    cliente_proposta: ClienteGranatech, fabrica: sessionmaker[Session]
) -> None:
    consulta_id, _ = _consulta_pronta(cliente_proposta)

    with pytest.raises(ErroGranatech) as erro:
        cliente_proposta.criar_proposta(consulta_id=consulta_id, corpo=_corpo("inexistente"))

    assert erro.value.status == 400
    assert not isinstance(erro.value, ErroIncerto)
    with fabrica() as sessao:
        assert sessao.scalars(select(PropostaGranatech.estado_envio)).one() == "falhou"
