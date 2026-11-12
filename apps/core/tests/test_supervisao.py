"""Lista do painel para supervisionar a IA: prévia, espera, atenção e ordem."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import etapa_do_estado
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, Mensagem
from saturday.dados.sessao import sessao as abrir
from saturday.painel.supervisao import PREVIA_MAXIMA, ordenar, supervisao

AGORA = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def test_etapa_vem_do_clt_ou_marca_inss() -> None:
    assert etapa_do_estado({"clt": {"etapa": "oferta"}}) == "oferta"
    assert etapa_do_estado({"publico": "inss"}) == "inss"
    assert etapa_do_estado({"hiscon": {"x": 1}}) == "inss"
    assert etapa_do_estado({"publico": "indefinido"}) is None


def _conversa(
    sessao: Session, nome: str, *, atendimento: str = "ia", etapa: str | None = None
) -> Conversa:
    conversa = Conversa(conversation_id=f"teste:{nome}", canal="whatsapp", atendimento=atendimento)
    conversa.etapa = etapa
    sessao.add(conversa)
    sessao.flush()
    return conversa


def _mensagem(
    sessao: Session,
    conversa: Conversa,
    direcao: str,
    minutos_atras: int,
    texto: str = "oi",
    **extra: object,
) -> None:
    sessao.add(
        Mensagem(
            conversa_id=conversa.id,
            direcao=direcao,
            autor="cliente" if direcao == "entrada" else "ia",
            conteudo=texto,
            criada_em=AGORA - timedelta(minutes=minutos_atras),
            **extra,
        )
    )
    sessao.flush()


def test_atencao_previa_e_ordem(fabrica: sessionmaker[Session]) -> None:
    with abrir(fabrica) as sessao:
        calma = _conversa(sessao, "calma")
        _mensagem(sessao, calma, "entrada", 30)
        _mensagem(sessao, calma, "saida", 29, "Posso ajudar?")

        esperando = _conversa(sessao, "esperando", atendimento="assumida")
        _mensagem(sessao, esperando, "entrada", 12, "alguém aí?")

        recente = _conversa(sessao, "recente")
        _mensagem(sessao, recente, "entrada", 2)

        handoff = _conversa(sessao, "handoff", atendimento="handoff")
        _mensagem(sessao, handoff, "entrada", 1, "x" * 500)
        repositorios.abrir_alerta(
            sessao, "handoff", conversa_id=handoff.id, detalhe={"motivo": "aceite_clt"}
        )

        oferta = _conversa(sessao, "oferta", etapa="oferta")
        _mensagem(sessao, oferta, "saida", 3, "Boa notícia")

        falhou = _conversa(sessao, "falhou")
        _mensagem(
            sessao,
            falhou,
            "saida",
            4,
            "",
            status_entrega="failed",
            anexos=[{"mime_type": "image/jpeg"}],
        )

        conversas = [calma, esperando, recente, handoff, oferta, falhou]
        campos = supervisao(sessao, conversas, AGORA)

        assert campos[calma.id]["atencao"] == []
        assert campos[calma.id]["aguardando_desde"] is None
        assert campos[calma.id]["ultima_mensagem"]["autor"] == "ia"
        assert campos[esperando.id]["atencao"] == ["sem_resposta"]
        assert campos[recente.id]["atencao"] == []
        assert campos[recente.id]["aguardando_desde"] == AGORA - timedelta(minutes=2)
        assert campos[handoff.id]["atencao"] == ["handoff"]
        assert campos[handoff.id]["motivo_handoff"] == "aceite_clt"
        assert len(campos[handoff.id]["ultima_mensagem"]["texto"]) == PREVIA_MAXIMA
        assert campos[oferta.id]["atencao"] == ["dinheiro"]
        assert campos[falhou.id]["atencao"] == ["envio_falhou"]
        assert campos[falhou.id]["ultima_mensagem"]["texto"] == "[Foto]"

        resumos = [
            {
                "id": c.conversation_id,
                **campos[c.id],
                "ultima_atividade": campos[c.id]["ultima_mensagem"]["em"],
            }
            for c in conversas
        ]
        ordem = [r["id"] for r in ordenar(resumos)]
        # Atenção primeiro, pela espera mais longa; depois por atividade recente.
        assert ordem[:4] == ["teste:esperando", "teste:falhou", "teste:oferta", "teste:handoff"]
        assert ordem[4:] == ["teste:recente", "teste:calma"]
