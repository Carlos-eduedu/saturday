"""Estado de atendimento em `conversas` (docs/decisoes/0003). Exige Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import resultado_jev
from sqlalchemy import func, select

from saturday.dados import atendimento, repositorios
from saturday.dados.modelos import (
    Alerta,
    Auditoria,
    Conversa,
    Mensagem,
    Outbox,
    Turno,
    UsuarioPainel,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.schemas import ChatRequest

TZ = ZoneInfo("America/Sao_Paulo")


def _conversa(fabrica, conversation_id):
    with abrir_sessao(fabrica) as sessao:
        conversa = repositorios.buscar_conversa(sessao, conversation_id)
        assert conversa is not None
        sessao.expunge(conversa)
        return conversa


def _atendente(fabrica, email="ana@exemplo.test"):
    with abrir_sessao(fabrica) as sessao:
        usuario = UsuarioPainel(email=email, nome="Atendente", senha_hash="x", perfil="atendente")
        sessao.add(usuario)
        sessao.flush()
        return usuario.id


def _assumir(fabrica, conversation_id, usuario_id):
    with abrir_sessao(fabrica) as sessao:
        conversa = repositorios.buscar_conversa(sessao, conversation_id)
        atendimento.assumir(sessao, conversa, usuario_id)


def _saidas(fabrica, conversation_id):
    with abrir_sessao(fabrica) as sessao:
        return sessao.scalar(
            select(func.count())
            .select_from(Mensagem)
            .join(Conversa)
            .where(Conversa.conversation_id == conversation_id, Mensagem.direcao == "saida")
        )


def test_handoff_do_grafo_vai_para_conversas_com_alerta(service_pg, fakes, fabrica, conversa):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="humano"))

    assert resposta.status == "handoff"
    assert _conversa(fabrica, conversa).atendimento == "handoff"
    with abrir_sessao(fabrica) as sessao:
        alerta = sessao.scalars(select(Alerta)).one()
        assert alerta.tipo == "handoff"


def test_conversa_assumida_cala_a_ia(service_pg, fakes, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    _assumir(fabrica, conversa, _atendente(fabrica))
    saidas = _saidas(fabrica, conversa)

    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="e aí?"))

    assert resposta.status == "with_human"
    assert len(fakes.jev.chamadas) == 1
    assert _saidas(fabrica, conversa) == saidas


def test_liberacao_automatica_nao_solta_conversa_assumida(
    service_pg, fakes, fabrica, conversa, monkeypatch
):
    service_pg.settings.handoff_auto_release_horas = 1
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    _assumir(fabrica, conversa, _atendente(fabrica))
    daqui_a_um_dia = datetime.now(TZ) + timedelta(days=1)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: daqui_a_um_dia)

    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi?"))

    assert resposta.status == "with_human"
    assert _conversa(fabrica, conversa).atendimento == "assumida"


def test_liberacao_automatica_solta_handoff_vencido(
    service_pg, fakes, fabrica, conversa, monkeypatch
):
    service_pg.settings.handoff_auto_release_horas = 1
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="humano"))
    daqui_a_duas_horas = datetime.now(TZ) + timedelta(hours=2)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: daqui_a_duas_horas)

    fakes.jev.resultado = resultado_jev()
    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    assert resposta.status == "answered"
    assert _conversa(fabrica, conversa).atendimento == "ia"


def test_release_devolve_no_banco(client_pg, fakes, fabrica, conversa):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    client_pg.post("/chat", json={"conversation_id": conversa, "message": "humano"})

    assert client_pg.post(f"/conversations/{conversa}/release").status_code == 200

    assert _conversa(fabrica, conversa).atendimento == "ia"
    fakes.jev.resultado = resultado_jev()
    resposta = client_pg.post("/chat", json={"conversation_id": conversa, "message": "oi"})
    assert resposta.json()["status"] == "answered"


def test_handoff_antigo_so_no_checkpoint_continua_valendo(service_pg, fakes, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    service_pg.graph.update_state(
        service_pg.config(conversa),
        {"status": "handoff", "handoff_em": datetime.now(TZ).isoformat()},
    )

    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    assert resposta.status == "with_human"
    assert _conversa(fabrica, conversa).atendimento == "handoff"


def test_handoff_antigo_abre_um_alerta_so(service_pg, fakes, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    service_pg.graph.update_state(
        service_pg.config(conversa),
        {"status": "handoff", "handoff_em": datetime.now(TZ).isoformat()},
    )

    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="alguém aí?"))

    with abrir_sessao(fabrica) as sessao:
        abertos = sessao.scalars(select(Alerta).where(Alerta.resolvido_em.is_(None))).all()
        assert [a.tipo for a in abertos] == ["handoff"]


def test_alerta_unico_reaproveita_o_aberto(service_pg, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    with abrir_sessao(fabrica) as sessao:
        conversa_id = repositorios.buscar_conversa(sessao, conversa).id
        primeiro = repositorios.abrir_alerta(sessao, "handoff", conversa_id=conversa_id)
        segundo = repositorios.abrir_alerta(sessao, "handoff", conversa_id=conversa_id, unico=True)
        outro_tipo = repositorios.abrir_alerta(
            sessao, "erro_interno", conversa_id=conversa_id, unico=True
        )
        assert segundo.id == primeiro.id
        assert outro_tipo.id != primeiro.id


def test_erro_interno_vai_para_handoff_com_alerta(service_pg, fabrica, conversa, monkeypatch):
    def quebra(*_args, **_kwargs):
        raise RuntimeError("grafo caiu")

    monkeypatch.setattr(service_pg.graph, "stream", quebra)
    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    assert resposta.status == "handoff"
    assert _conversa(fabrica, conversa).atendimento == "handoff"
    with abrir_sessao(fabrica) as sessao:
        assert [a.tipo for a in sessao.scalars(select(Alerta))] == ["erro_interno"]


def test_erro_interno_grava_o_aviso_no_historico_e_no_outbox(
    service_pg, fabrica, conversa, monkeypatch
):
    """Decisão 7 do plano: o aviso de erro interno aparece no painel e sai pelo outbox."""

    from saturday.canais.base import OrigemCanal

    def quebra(*_args, **_kwargs):
        raise RuntimeError("grafo caiu")

    monkeypatch.setattr(service_pg.graph, "stream", quebra)
    origem = OrigemCanal(canal="whatsapp", telefone="11987654321", phone_number_id="1000001")
    resposta = service_pg.process_message(
        ChatRequest(conversation_id=conversa, message="oi"), origem
    )

    with abrir_sessao(fabrica) as sessao:
        [saida] = sessao.scalars(select(Mensagem).where(Mensagem.direcao == "saida")).all()
        [turno] = sessao.scalars(select(Turno)).all()
        [envio] = sessao.scalars(select(Outbox)).all()
        assert saida.conteudo == resposta.answer
        assert saida.turno_id == turno.id and turno.erro == "RuntimeError"
        assert saida.chave_mensagem in (
            "handoff:erro_interno",
            "handoff:erro_interno+textos:fora_horario",
        )
        assert envio.payload["mensagem_id"] == saida.id
        assert envio.payload["handoff_reason"] == "erro_interno"


# ------------------------------------------------- devolver em uma operação


def _alertas(fabrica):
    """Tipo e quem resolveu cada alerta; aberto aparece como `"aberto"`."""

    with abrir_sessao(fabrica) as sessao:
        return [
            (a.tipo, "aberto" if a.resolvido_em is None else a.resolvido_por)
            for a in sessao.scalars(select(Alerta).order_by(Alerta.id))
        ]


def _em_handoff(service, fakes, conversation_id):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    service.process_message(ChatRequest(conversation_id=conversation_id, message="humano"))
    fakes.jev.resultado = resultado_jev()


def test_devolver_resolve_o_alerta_e_zera_o_checkpoint(service_pg, fakes, fabrica, conversa):
    _em_handoff(service_pg, fakes, conversa)
    ana = _atendente(fabrica)

    service_pg.devolver(_conversa(fabrica, conversa).id, ana, gestor=False)

    assert _conversa(fabrica, conversa).atendimento == "ia"
    assert _alertas(fabrica) == [("handoff", ana)]
    assert service_pg.estado_atual(service_pg.config(conversa))["status"] == "in_progress"


def test_devolver_com_o_checkpoint_falhando_nao_muda_nada(
    service_pg, fakes, fabrica, conversa, monkeypatch
):
    _em_handoff(service_pg, fakes, conversa)

    def checkpoint_fora_do_ar(*_args, **_kwargs):
        raise RuntimeError("falha proposital")

    monkeypatch.setattr(service_pg.graph, "update_state", checkpoint_fora_do_ar)
    with pytest.raises(RuntimeError, match="falha proposital"):
        service_pg.devolver(_conversa(fabrica, conversa).id, _atendente(fabrica), gestor=False)

    # Banco em `ia` com checkpoint em `handoff` reabriria o handoff sozinho.
    assert _conversa(fabrica, conversa).atendimento == "handoff"
    assert _alertas(fabrica) == [("handoff", "aberto")]
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(Auditoria)).all() == []


def test_liberacao_automatica_resolve_o_alerta_sem_usuario(
    service_pg, fakes, fabrica, conversa, monkeypatch
):
    service_pg.settings.handoff_auto_release_horas = 1
    _em_handoff(service_pg, fakes, conversa)
    daqui_a_duas_horas = datetime.now(TZ) + timedelta(hours=2)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: daqui_a_duas_horas)

    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    assert _alertas(fabrica) == [("handoff", None)]


def test_release_resolve_o_alerta_sem_usuario(client_pg, fakes, fabrica, conversa):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    client_pg.post("/chat", json={"conversation_id": conversa, "message": "humano"})

    assert client_pg.post(f"/conversations/{conversa}/release").status_code == 200

    assert _alertas(fabrica) == [("handoff", None)]
