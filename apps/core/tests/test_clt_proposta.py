"""Proposta e pós-venda do ramo CLT (Fase 6), ponta a ponta.

Mesmo arranjo das jornadas da Fase 5 (`test_clt_jornada.py`): Postgres real,
simulador da Granatech em processo, BrasilAPI falsa e Jev/LLM falsos.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from conftest import _montar_app
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_clt_jornada import (  # noqa: F401 - fixtures
    Jornada,
    _ate_oferta,
    brasilapi,
    fakes_clt,
)
from test_clt_jornada import nova as _nova_fase5  # noqa: F401

from saturday.agent.clt.mensagens import texto
from saturday.dados.modelos import Alerta, Consentimento, Conversa, Mensagem, Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import granatech as eventos_granatech

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

DOMINIO = "saturday.exemplo"
DADOS_ATE_RESUMO = ("quero", "sim", "sim", "casado", "itau", "corrente", "1234", "12345-6", "sim")


@pytest.fixture
def nova(_nova_fase5: Any) -> Any:  # noqa: F811
    def criar(**extras: Any) -> Jornada:
        base = {"granatech_proposta_ativa": True, "dominio_publico": DOMINIO}
        jornada: Jornada = _nova_fase5(**{**base, **extras})
        return jornada

    return criar


def _proposta(jornada: Jornada) -> str:
    return str(jornada.clt()["proposta"])


def _evento(jornada: Jornada, status: str, notificacao: str | None, **extras: Any) -> None:
    payload = {
        "tipo": "proposta",
        "status_da_proposta": status,
        "tipo_notificacao": notificacao,
        "id_proposta": _proposta(jornada),
        **extras,
    }
    eventos_granatech.aplicar(jornada.fabrica, jornada.cliente, payload, jornada.servico)


def _saidas(jornada: Jornada) -> int:
    with abrir_sessao(jornada.fabrica) as sessao:
        return int(
            sessao.scalar(
                select(func.count())
                .select_from(Mensagem)
                .join(Conversa, Conversa.id == Mensagem.conversa_id)
                .where(Conversa.conversation_id == jornada.id, Mensagem.direcao == "saida")
            )
            or 0
        )


def _ultimo_payload(jornada: Jornada) -> dict[str, Any]:
    with abrir_sessao(jornada.fabrica) as sessao:
        payload = sessao.scalars(select(Outbox.payload).order_by(Outbox.id.desc())).first()
        return dict(payload or {})


def _ate_proposta(jornada: Jornada) -> None:
    _ate_oferta(jornada)
    resumo = jornada.roteiro(*DADOS_ATE_RESUMO)
    assert resumo.answer.startswith("Confira o resumo da proposta")
    assert jornada.falar("SIM").answer == texto("proposta_enviada")


def _atendimento(jornada: Jornada) -> str:
    with abrir_sessao(jornada.fabrica) as sessao:
        return str(
            sessao.scalars(
                select(Conversa.atendimento).where(Conversa.conversation_id == jornada.id)
            ).one()
        )


# ---------------------------------------------------------------- caminho feliz


def test_jornada_completa_ate_o_pagamento(
    nova: Any, fabrica: sessionmaker[Session], simulador_granatech: ModuleType
) -> None:
    jornada = nova()
    _ate_oferta(jornada)

    assert jornada.falar("quero").answer == texto("confirmar_mae", mae="MAE DE TESTE DA SILVA")
    endereco = jornada.falar("sim").answer
    assert "PRACA DA SE, 100" in endereco and "SAO PAULO/SP" in endereco
    assert jornada.falar("sim").answer == texto("pedir_estado_civil")
    assert jornada.falar("casado").answer == texto("pedir_banco")
    assert jornada.falar("itaú").answer == texto("pedir_tipo_conta")
    jornada.roteiro("corrente", "1234", "12345-6")
    resumo = jornada.falar("sim").answer
    assert "conta final 45-6 do Itaú" in resumo
    assert "seguro Super Proteção" in resumo and "opcional" in resumo

    assert jornada.falar("SIM").answer == texto("proposta_enviada")
    propostas = list(simulador_granatech.PROPOSTAS.values())
    assert len(propostas) == 1
    tomador = propostas[0]["dados_tomador"]
    assert tomador["estado_civil"] == "CASADO"
    assert tomador["nome_completo_mae"] == "MAE DE TESTE DA SILVA"
    assert tomador["banco_detalhe"] == {
        "agencia": "1234",
        "digito_agencia": "",
        "numero_conta": "12345",
        "digito_conta": "6",
        "tipo_conta": "conta_corrente",
        "banco_codigo": "341",
    }
    with abrir_sessao(fabrica) as sessao:
        prova = sessao.scalars(select(Consentimento).where(Consentimento.tipo == "proposta")).one()
        assert prova.texto_mostrado == resumo
        assert prova.resposta_literal == "SIM"

    _evento(jornada, "PENDING_CONFIRMATION", "AGUARDANDO_CONFIRMACAO")
    assert jornada.ultima_saida() == texto("aviso_criada")

    _evento(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO")
    aviso = jornada.ultima_saida()
    assert f"https://{DOMINIO}/l/" in aviso
    payload = _ultimo_payload(jornada)
    assert payload["modelo_aviso"] == "assinatura_pronta"
    assert aviso.endswith(payload["link_aviso"])
    assert jornada.clt()["etapa"] == "formalizacao"

    # Duplicado e "só atualiza": nenhuma mensagem nova.
    antes = _saidas(jornada)
    _evento(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO", informacoes="de novo")
    _evento(jornada, "PENDING_FORMALIZATION", "BLOQUEIO_DE_SALDO_EM_ANDAMENTO")
    _evento(jornada, "PENDING_FORMALIZATION", "FORMALIZACAO_EM_ANDAMENTO")
    assert _saidas(jornada) == antes

    _evento(jornada, "PENDING_REFORMALIZATION", "REFAZER_SEGURANCA_IDENTIDADE")
    refazer = jornada.ultima_saida()
    assert refazer.startswith("O banco pediu para refazer") and payload["link_aviso"] in refazer
    assert _ultimo_payload(jornada)["modelo_aviso"] == "assinatura_refazer"

    _evento(jornada, "PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO")
    assert jornada.ultima_saida() == texto("aviso_analise")
    _evento(jornada, "PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE")
    assert jornada.ultima_saida() == texto("aviso_identidade_ok")
    assert jornada.falar("e agora").answer == texto("acompanhando")

    _evento(jornada, "PENDING_PAYMENT", "PAGO")
    assert jornada.ultima_saida() == texto("aviso_paga")
    assert _ultimo_payload(jornada)["modelo_aviso"] == "pagamento_confirmado"
    assert jornada.clt()["etapa"] == "pago"

    # Depois de pago, evento atrasado não fala e o cliente só tem a FAQ.
    antes = _saidas(jornada)
    _evento(jornada, "PENDING_BANK_ANALYSIS", "AGUARDANDO_ANALISE_BANCO")
    assert _saidas(jornada) == antes
    resposta = jornada.falar("quando cai?")
    assert resposta.status == "answered" and jornada.clt()["etapa"] == "pago"


# ---------------------------------------------------------------- proposta única


def _posts_de_proposta(simulador: ModuleType) -> int:
    return sum(
        1
        for metodo, caminho in simulador.CHAMADAS
        if metodo == "POST" and caminho.endswith("/propostas")
    )


def test_timeout_com_proposta_criada_reconcilia_sem_novo_post(
    nova: Any, simulador_granatech: ModuleType, http_granatech: TestClient
) -> None:
    simulador_granatech.CONFIG["timeout_s"] = 0
    http_granatech.post(
        "/admin/falha",
        json={"rota": "/propostas", "metodo": "POST", "status": "timeout", "registrar": True},
    )
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)

    assert jornada.falar("SIM").answer == texto("proposta_enviada")
    assert len(simulador_granatech.PROPOSTAS) == 1
    assert _posts_de_proposta(simulador_granatech) == 1
    assert jornada.clt()["proposta"] in simulador_granatech.PROPOSTAS


def test_timeout_sem_proposta_vai_para_handoff_sem_novo_post(
    nova: Any, simulador_granatech: ModuleType, http_granatech: TestClient
) -> None:
    simulador_granatech.CONFIG["timeout_s"] = 0
    http_granatech.post(
        "/admin/falha", json={"rota": "/propostas", "metodo": "POST", "status": "timeout"}
    )
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)

    resposta = jornada.falar("SIM")
    assert resposta.status == "handoff" and resposta.handoff_reason == "proposta_incerta"
    assert not simulador_granatech.PROPOSTAS
    assert _posts_de_proposta(simulador_granatech) == 1


# ---------------------------------------------------------------- dados e aceite


def test_mae_divergente_vai_para_handoff(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.falar("quero")
    resposta = jornada.falar("não")
    assert resposta.status == "handoff" and resposta.handoff_reason == "dados_divergentes"


def test_conta_de_terceiro_volta_ao_banco(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO[:-1])
    resposta = jornada.falar("não")
    assert resposta.answer == f"{texto('conta_de_terceiro')}\n\n{texto('pedir_banco')}"
    assert jornada.clt()["passo"] == "banco"


def test_banco_ambiguo_mostra_lista(nova: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    jornada = nova()
    bancos = [
        {"codigo": "001", "nome": "Banco do Brasil", "habilitado": True},
        {"codigo": "422", "nome": "Banco Safra", "habilitado": True},
    ]
    monkeypatch.setattr(jornada.cliente, "bancos", lambda: bancos)
    _ate_oferta(jornada)
    jornada.roteiro("quero", "sim", "sim", "solteiro")
    lista = jornada.falar("banco").answer
    assert lista.startswith(texto("escolher_banco"))
    assert "1. Banco do Brasil (001)" in lista
    assert jornada.falar("1").answer == texto("pedir_tipo_conta")
    assert jornada.clt()["dados"]["conta_nova"]["banco_codigo"] == "001"


def test_negar_o_resumo_volta_para_a_oferta(nova: Any, simulador_granatech: ModuleType) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    jornada.roteiro(*DADOS_ATE_RESUMO)
    assert jornada.falar("não").answer == texto("aceite_recusado")
    assert jornada.clt()["etapa"] == "oferta"
    assert not simulador_granatech.PROPOSTAS


def test_oferta_sem_seguro_vai_para_handoff(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    clt = jornada.clt()
    clt["oferta"]["seguro_aplicado"] = False
    jornada.servico.graph.update_state(jornada.servico.config(jornada.id), {"clt": clt})
    resposta = jornada.falar("quero")
    assert resposta.status == "handoff" and resposta.handoff_reason == "proposta_sem_seguro"


# ---------------------------------------------------------------- pós-venda


def test_pedido_de_cancelamento_vai_para_handoff(nova: Any) -> None:
    jornada = nova()
    _ate_proposta(jornada)
    resposta = jornada.falar("quero cancelar")
    assert resposta.status == "handoff" and resposta.handoff_reason == "pediu_cancelamento"


def test_revisao_do_banco_faz_handoff_com_as_informacoes(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    _ate_proposta(jornada)
    _evento(
        jornada, "PENDING_USER_REVIEW", "AGUARDANDO_REVISAO_USUARIO", informacoes="CPF divergente"
    )
    assert _atendimento(jornada) == "handoff"
    with abrir_sessao(fabrica) as sessao:
        alerta = sessao.scalars(
            select(Alerta).where(Alerta.tipo == "handoff").order_by(Alerta.id.desc())
        ).first()
        assert alerta is not None
        assert alerta.detalhe == {"motivo": "revisao_banco", "informacoes": "CPF divergente"}


def test_status_desconhecido_faz_handoff(nova: Any) -> None:
    jornada = nova()
    _ate_proposta(jornada)
    _evento(jornada, "STATUS_NOVO", "NOTIFICACAO_NOVA")
    assert _atendimento(jornada) == "handoff"


@pytest.mark.parametrize(
    ("status", "notificacao", "informacoes", "chave", "valores"),
    [
        ("REPROVED", "REPROVADO", None, "aviso_reprovada", {}),
        (
            "CANCELED",
            "CANCELADO",
            "Margem insuficiente",
            "aviso_cancelada_motivo",
            {"motivo": "Margem insuficiente"},
        ),
        ("CANCELED", None, {"codigo": 7}, "aviso_cancelada", {}),
    ],
)
def test_reprovada_ou_cancelada_encerra(
    nova: Any,
    status: str,
    notificacao: str | None,
    informacoes: Any,
    chave: str,
    valores: dict[str, str],
) -> None:
    jornada = nova()
    _ate_proposta(jornada)
    _evento(jornada, status, notificacao, informacoes=informacoes)
    assert jornada.ultima_saida() == texto(chave, **valores)
    assert jornada.clt()["etapa"] == "encerrada"


def _falha_de_pagamento(jornada: Jornada) -> None:
    _evento(jornada, "PENDING_USER_REVIEW", "FALHA_PAGAMENTO")
    assert jornada.ultima_saida() == f"{texto('aviso_falha_pagamento')}\n\n{texto('pedir_banco')}"
    assert _ultimo_payload(jornada)["modelo_aviso"] == "dados_bancarios_pendentes"


def test_falha_de_pagamento_sem_patch_coleta_e_passa(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    _ate_proposta(jornada)
    _falha_de_pagamento(jornada)
    jornada.roteiro("001", "poupança", "4321-0")
    jornada.falar("998877")
    resposta = jornada.falar("sim")
    assert resposta.status == "handoff" and resposta.handoff_reason == "falha_pagamento"
    with abrir_sessao(fabrica) as sessao:
        alerta = sessao.scalars(
            select(Alerta).where(Alerta.tipo == "handoff").order_by(Alerta.id.desc())
        ).first()
        assert alerta is not None
        assert alerta.detalhe["conta"]["numero_conta"] == "99887"
        assert alerta.detalhe["conta"]["banco_codigo"] == "001"


def test_falha_de_pagamento_com_patch_e_segunda_falha(
    nova: Any, simulador_granatech: ModuleType
) -> None:
    jornada = nova(granatech_dados_bancarios_ativo=True)
    _ate_proposta(jornada)
    _falha_de_pagamento(jornada)
    jornada.roteiro("001", "poupança", "4321-0", "998877")
    assert jornada.falar("sim").answer == texto("conta_corrigida")
    corpo = simulador_granatech.PROPOSTAS[_proposta(jornada)]["dados_bancarios"]
    assert corpo["banco_detalhe"]["agencia"] == "4321"

    _evento(jornada, "PENDING_PAYMENT", "SUCESSO_SEGURANCA_IDENTIDADE")
    _evento(jornada, "PENDING_USER_REVIEW", "FALHA_PAGAMENTO")
    assert _atendimento(jornada) == "handoff"


# ---------------------------------------------------------------- link curto


@pytest.fixture
def api(nova: Any, fabrica: sessionmaker[Session]) -> Iterator[tuple[Jornada, TestClient]]:
    jornada = nova()
    # Sem `with`: o lifespan montaria outro serviço e outra fábrica.
    yield jornada, TestClient(_montar_app(jornada.servico.settings, jornada.servico, fabrica))


def test_link_curto_redireciona_ao_link_vigente(
    api: tuple[Jornada, TestClient], simulador_granatech: ModuleType, http_granatech: TestClient
) -> None:
    jornada, cliente = api
    _ate_proposta(jornada)
    _evento(jornada, "PENDING_FORMALIZATION", "AGUARDANDO_FORMALIZACAO")
    codigo = _ultimo_payload(jornada)["link_aviso"]
    id_proposta = _proposta(jornada)

    resposta = cliente.get(f"/l/{codigo}", follow_redirects=False)
    assert resposta.status_code == 302
    assert resposta.headers["location"] == f"https://biometria.simulador/{id_proposta}/v1"

    simulador_granatech.PROPOSTAS[id_proposta]["versao_link"] = 2
    resposta = cliente.get(f"/l/{codigo}", follow_redirects=False)
    assert resposta.headers["location"].endswith("/v2")

    # Granatech fora: vale a última URL conhecida.
    http_granatech.post(
        "/admin/falha",
        json={"rota": f"/propostas/{id_proposta}", "metodo": "GET", "status": 500, "vezes": 2},
    )
    resposta = cliente.get(f"/l/{codigo}", follow_redirects=False)
    assert resposta.headers["location"].endswith("/v2")

    assert cliente.get("/l/naoexiste", follow_redirects=False).status_code == 404
