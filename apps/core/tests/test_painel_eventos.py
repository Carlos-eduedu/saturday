"""Tempo real (pg_notify → SSE) e alertas do worker. Exige Postgres."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import psycopg
from sqlalchemy import func, select, update

from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, Conversa, Mensagem, Outbox
from saturday.dados.outbox import enfileirar, marcar_desistencia
from saturday.dados.sessao import sessao as abrir
from saturday.jobs import alertas
from saturday.painel import sessoes
from saturday.web.eventos import Difusor, fluxo_sse


def _ouvinte(pg_url):
    conexao = psycopg.connect(pg_url, autocommit=True)
    conexao.execute("LISTEN painel")
    return conexao


def _avisos(conexao):
    return [json.loads(n.payload) for n in conexao.notifies(timeout=0.5)]


def test_aviso_so_sai_no_commit(fabrica, pg_url, conversa):
    with _ouvinte(pg_url) as conexao:
        sessao = fabrica()
        repositorios.obter_ou_criar_conversa(sessao, conversa)
        repositorios.abrir_alerta(sessao, "handoff")
        sessao.rollback()
        sessao.close()
        assert _avisos(conexao) == []

        with abrir(fabrica) as s:
            alerta = repositorios.abrir_alerta(s, "handoff")
        assert _avisos(conexao) == [{"tipo": "alerta", "alerta": str(alerta.id)}]


def test_difusor_repassa_o_aviso_para_quem_assina(fabrica, pg_url):
    async def cenario():
        difusor = Difusor(pg_url)
        difusor.iniciar()
        fila = difusor.assinar()
        try:
            await asyncio.sleep(0.5)  # tempo do LISTEN
            await asyncio.to_thread(_gravar_alerta, fabrica)
            return await asyncio.wait_for(fila.get(), timeout=3)
        finally:
            await difusor.parar()

    assert json.loads(asyncio.run(cenario()))["tipo"] == "alerta"


def _gravar_alerta(fabrica):
    with abrir(fabrica) as s:
        repositorios.abrir_alerta(s, "handoff")


def test_fluxo_sse_formata_e_manda_keepalive():
    async def cenario():
        fila: asyncio.Queue[str] = asyncio.Queue()
        fila.put_nowait('{"tipo":"conversa"}')
        fluxo = fluxo_sse(fila, keepalive_s=0.05)
        return [await anext(fluxo), await anext(fluxo)]

    assert asyncio.run(cenario()) == ['data: {"tipo":"conversa"}\n\n', ": keepalive\n\n"]


def test_eventos_exige_sessao(client_pg):
    assert client_pg.get("/admin/eventos").status_code == 401


# ------------------------------------------------------------------ alertas


def _conversa_assumida(fabrica, conversation_id, minutos_atras):
    with abrir(fabrica) as s:
        usuario = sessoes.criar_usuario(s, f"{conversation_id}@exemplo.test", "x" * 12, "atendente")
        conversa = repositorios.obter_ou_criar_conversa(s, conversation_id, canal="whatsapp")
        repositorios.registrar_entrada(s, conversa, message_id=None, conteudo="oi?")
        repositorios.mudar_atendimento(s, conversa, "assumida", atendente_id=usuario.id)
        s.execute(
            update(Conversa)
            .where(Conversa.id == conversa.id)
            .values(ultima_entrada_em=func.now() - timedelta(minutes=minutos_atras))
        )
        return conversa.id


def _sem_resposta(fabrica):
    with abrir(fabrica) as s:
        return s.scalar(
            select(func.count()).select_from(Alerta).where(Alerta.tipo == "sem_resposta")
        )


def test_cliente_sem_resposta_ha_10_min_gera_um_alerta_so(fabrica, conversa):
    _conversa_assumida(fabrica, conversa, minutos_atras=11)

    assert alertas.verificar(fabrica) == 1
    assert alertas.verificar(fabrica) == 0
    assert _sem_resposta(fabrica) == 1


def test_sem_alerta_antes_de_10_min_ou_com_resposta(fabrica, conversa):
    _conversa_assumida(fabrica, conversa, minutos_atras=5)
    respondida = _conversa_assumida(fabrica, conversa + "-b", minutos_atras=11)
    with abrir(fabrica) as s:
        s.add(
            Mensagem(conversa_id=respondida, direcao="saida", autor="atendente", conteudo="já vou")
        )

    assert alertas.verificar(fabrica) == 0


def test_envio_que_desiste_abre_alerta(fabrica, conversa):
    with abrir(fabrica) as s:
        linha_conversa = repositorios.obter_ou_criar_conversa(s, conversa, canal="whatsapp")
        linha = enfileirar(s, conversa_id=linha_conversa.id, canal="whatsapp", payload={})
        marcar_desistencia(s, linha, erro="permanente: 400")
    with abrir(fabrica) as s:
        [alerta] = s.scalars(select(Alerta)).all()
        assert alerta.tipo == "envio_falhou"
        assert alerta.detalhe == {"outbox": s.scalar(select(Outbox.id))}
