"""Aba Agente: grafo compilado e execuções de todas as conversas. Exige Postgres."""

from __future__ import annotations

from sqlalchemy import select

from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.sessao import sessao as abrir
from saturday.painel import sessoes
from saturday.schemas import ChatRequest

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
WHATSAPP = OrigemCanal(canal="whatsapp", telefone="11987654321", phone_number_id="100000000000001")


def _entrar(client, fabrica, email, perfil):
    with abrir(fabrica) as s:
        sessoes.criar_usuario(s, email, SENHA, perfil)
    client.cookies.clear()
    assert client.post("/admin/login", json={"email": email, "senha": SENHA}).status_code == 200


def _turnos(fabrica, conversa):
    with abrir(fabrica) as s:
        conversa_db = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        return list(s.scalars(select(Turno).where(Turno.conversa_id == conversa_db.id)))


def test_grafo_e_o_compilado_com_modelo_e_passagens(client_pg, service_pg, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), WHATSAPP)
    _entrar(client_pg, fabrica, "ana-grafo@exemplo.test", "atendente")

    grafo = client_pg.get("/admin/agente/grafo").json()
    nos = {n["id"]: n for n in grafo["nos"]}
    assert {"__start__", "__end__", "classify_intent", "clt", "handoff"} <= nos.keys()
    assert {"de": "__start__", "para": "clt", "condicional": True} in grafo["arestas"]
    assert {"de": "handoff", "para": "__end__", "condicional": False} in grafo["arestas"]
    assert nos["classify_intent"]["modelo"]["variavel"] == "SATURDAY_JEV_MODEL"
    assert nos["calculate_portability"]["modelo"] is None
    assert all(n["descricao"] for n in grafo["nos"])
    assert nos["classify_intent"]["passagens_24h"] == 1
    assert nos["__start__"]["passagens_24h"] == 1


def test_execucoes_filtram_e_escondem_custo_de_atendente(
    client_pg, service_pg, fabrica, conversa, monkeypatch
):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), WHATSAPP)

    def quebra(*_args, **_kwargs):
        raise TimeoutError("segredo 123.456.789-09")

    monkeypatch.setattr(service_pg.graph, "stream", quebra)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="e aí"), WHATSAPP)

    ok, quebrado = sorted(_turnos(fabrica, conversa), key=lambda t: t.id)
    assert ok.duracao_ms is not None and ok.erro is None
    # Só o nome da exceção: a mensagem pode ter dado do cliente.
    assert quebrado.erro == "TimeoutError" and quebrado.status == "handoff"

    _entrar(client_pg, fabrica, "ana-exec@exemplo.test", "atendente")
    todas = client_pg.get("/admin/agente/execucoes").json()
    assert [e["id"] for e in todas["execucoes"]] == [quebrado.id, ok.id]
    assert todas["execucoes"][0]["telefone"] == "(11) *****-4321"
    assert all(e["custo_usd"] is None and e["tokens"] is None for e in todas["execucoes"])
    assert todas["tem_mais"] is False

    erros = client_pg.get("/admin/agente/execucoes", params={"situacao": "erro"}).json()
    assert [e["id"] for e in erros["execucoes"]] == [quebrado.id]
    pelo_no = client_pg.get("/admin/agente/execucoes", params={"no": "classify_intent"}).json()
    assert [e["id"] for e in pelo_no["execucoes"]] == [ok.id]
    antes = client_pg.get("/admin/agente/execucoes", params={"antes_de": quebrado.id}).json()
    assert [e["id"] for e in antes["execucoes"]] == [ok.id]

    _entrar(client_pg, fabrica, "gestor-exec@exemplo.test", "gestor")
    gestor = client_pg.get("/admin/agente/execucoes").json()
    assert gestor["execucoes"][0]["custo_usd"] is not None


def test_agente_exige_login(client_pg):
    client_pg.cookies.clear()
    assert client_pg.get("/admin/agente/grafo").status_code == 401
    assert client_pg.get("/admin/agente/execucoes").status_code == 401
