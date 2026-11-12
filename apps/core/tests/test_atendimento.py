"""Estado de atendimento em `conversas` (docs/decisoes/0003). Exige Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import resultado_jev
from sqlalchemy import func, select

from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, Conversa, Mensagem, UsuarioPainel
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
        repositorios.mudar_atendimento(sessao, conversa, "assumida", atendente_id=usuario_id)


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


def test_erro_interno_vai_para_handoff_com_alerta(service_pg, fabrica, conversa, monkeypatch):
    def quebra(*_args, **_kwargs):
        raise RuntimeError("grafo caiu")

    monkeypatch.setattr(service_pg.graph, "stream", quebra)
    resposta = service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))

    assert resposta.status == "handoff"
    assert _conversa(fabrica, conversa).atendimento == "handoff"
    with abrir_sessao(fabrica) as sessao:
        assert [a.tipo for a in sessao.scalars(select(Alerta))] == ["erro_interno"]
