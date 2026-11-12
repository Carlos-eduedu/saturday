"""Trilha da IA por turno e custos: gravação, permissões e totais. Exige Postgres."""

from __future__ import annotations

import json

from sqlalchemy import select

from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import Conversa, Turno
from saturday.dados.sessao import sessao as abrir
from saturday.metrics import iniciar_metricas, registrar_chamada, uso_do_payload
from saturday.painel import sessoes
from saturday.schemas import ChatRequest

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
WHATSAPP = OrigemCanal(canal="whatsapp", telefone="11987654321", phone_number_id="100000000000001")


def _entrar(client, fabrica, email, perfil):
    with abrir(fabrica) as s:
        sessoes.criar_usuario(s, email, SENHA, perfil)
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200


def test_uso_le_custo_e_tokens_da_openrouter():
    dados = {"usage": {"cost": 0.0012, "prompt_tokens": 900, "completion_tokens": 40}}
    assert uso_do_payload(dados) == {"custo_usd": 0.0012, "tokens_entrada": 900, "tokens_saida": 40}
    assert uso_do_payload({}) == {}

    metricas = iniciar_metricas()
    registrar_chamada("llm", 12.3, status="ok", **uso_do_payload(dados))
    registrar_chamada("granatech", 50, status=200)
    resumo = metricas.resumo()
    assert resumo["tokens_total"] == 940
    assert resumo["chamadas"][1]["status"] == "200"


def test_turno_grava_trilha_sem_texto(service_pg, fabrica, conversa):
    service_pg.process_message(
        ChatRequest(conversation_id=conversa, message="meu cpf é 123.456.789-09"), WHATSAPP
    )
    with abrir(fabrica) as s:
        conversa_db = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        [turno] = s.scalars(select(Turno).where(Turno.conversa_id == conversa_db.id)).all()
        assert "classify_intent" in turno.caminho
        assert turno.classificacao is not None
        assert set(turno.classificacao) == {"intencao", "publico", "confianca"}
        serializado = json.dumps(
            [turno.caminho, turno.classificacao, turno.chamadas, turno.status, turno.motivo]
        )
        assert "123.456" not in serializado and "cpf" not in serializado.lower()


def test_trilha_para_todos_custo_so_para_gestor(client_pg, service_pg, fabrica, conversa):
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), WHATSAPP)
    with abrir(fabrica) as s:
        conversa_db = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        alvo = str(conversa_db.id)
        s.add(
            Turno(
                conversa_id=conversa_db.id,
                caminho=["classify_intent"],
                chamadas=[{"nome": "jev", "latencia_ms": 10, "custo_usd": 0.5, "status": "ok"}],
                custo_usd=0.5,
                tokens=1000,
            )
        )

    _entrar(client_pg, fabrica, "ana-trilha@exemplo.test", "atendente")
    trilha = client_pg.get(f"/admin/conversas/{alvo}/turnos").json()
    assert trilha["custo_usd"] is None and trilha["tokens"] is None
    assert len(trilha["turnos"]) == 2
    assert all(t["custo_usd"] is None for t in trilha["turnos"])
    assert all(c["custo_usd"] is None for t in trilha["turnos"] for c in t["chamadas"])
    assert client_pg.get("/admin/custos").status_code == 403

    _entrar(client_pg, fabrica, "gestor-trilha@exemplo.test", "gestor")
    trilha = client_pg.get(f"/admin/conversas/{alvo}/turnos").json()
    assert trilha["custo_usd"] == 0.5
    assert trilha["tokens"] == 1000

    custos = client_pg.get("/admin/custos").json()
    assert custos["total"]["custo_usd"] == 0.5
    assert custos["total"]["turnos"] == 2
    assert custos["hoje"]["custo_usd"] == 0.5
    assert custos["conversas_mais_caras"][0]["id"] == alvo
    assert custos["conversas_mais_caras"][0]["telefone"] == "(11) *****-4321"
