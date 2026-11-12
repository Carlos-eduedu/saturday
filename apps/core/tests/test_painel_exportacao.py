"""A conversa em Markdown: o arquivo que sai do painel para outra ferramenta."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from saturday.dados.modelos import (
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Mensagem,
    PropostaGranatech,
    Turno,
)
from saturday.painel import exportacao

# 14:00 em São Paulo: o arquivo mostra a hora da operação, não UTC.
AGORA = datetime(2025, 3, 12, 17, 0, tzinfo=UTC)

FICHA = {
    "nome": "Maria Souza",
    "dados": {
        "cpf": "***.***.***-67",
        "telefone": "(11) *****-4321",
        "data_nascimento": "**/**/1990",
        "email": "m***@exemplo.com",
    },
    "uf": "SP",
    "publico": "clt",
    "handoff_reason": None,
    "portabilidade": None,
}

SUPERVISAO = {"atencao": ["dinheiro"], "motivo_handoff": None}


def _conversa(**mudancas: Any) -> Conversa:
    campos: dict[str, Any] = {
        "id": uuid.uuid4(),
        "conversation_id": "whatsapp:11987654321",
        "canal": "whatsapp",
        "atendimento": "ia",
        "telefone": "11987654321",
        "etapa": "oferta",
        "criada_em": datetime(2025, 3, 12, 12, 0, tzinfo=UTC),
        "ultima_entrada_em": datetime(2025, 3, 12, 16, 0, tzinfo=UTC),
    }
    return Conversa(**{**campos, **mudancas})


def _retrato(**mudancas: Any) -> exportacao.Retrato:
    campos: dict[str, Any] = {
        "conversa": _conversa(),
        "ficha": FICHA,
        "supervisao": SUPERVISAO,
        "mensagens": (),
        "consentimentos": (),
        "consultas": (),
        "propostas": (),
        "turnos": (),
        "gestor": False,
        "exportado_em": AGORA,
        "exportado_por": "ana@exemplo.test",
    }
    return exportacao.Retrato(**{**campos, **mudancas})


def _mensagem(autor: str, texto: str, minuto: int, **mudancas: Any) -> Mensagem:
    campos: dict[str, Any] = {
        "id": minuto,
        "direcao": "entrada" if autor == "cliente" else "saida",
        "autor": autor,
        "conteudo": texto,
        "criada_em": datetime(2025, 3, 12, 12, minuto, tzinfo=UTC),
    }
    return Mensagem(**{**campos, **mudancas})


# ------------------------------------------------------------------ cabeçalho


def test_cabecalho_traz_a_jornada_e_o_telefone_mascarado():
    texto = exportacao.conversa_em_markdown(_retrato())

    assert texto.startswith("# Conversa — WhatsApp oficial · (11) *****-4321\n")
    assert "- **Atendimento:** IA" in texto
    assert "- **Etapa:** oferta" in texto
    assert "- **Cliente escreveu pela última vez em:** 2025-03-12 13:00" in texto
    assert "- **Janela de 24 h:** aberta" in texto
    assert "- **Alertas:** dinheiro" in texto
    assert "- **Exportado em:** 2025-03-12 14:00 por ana@exemplo.test" in texto


def test_janela_de_24h_aparece_so_no_whatsapp():
    fechada = exportacao.conversa_em_markdown(_retrato(conversa=_conversa(ultima_entrada_em=None)))
    assert "- **Janela de 24 h:** fechada" in fechada

    evolution = exportacao.conversa_em_markdown(_retrato(conversa=_conversa(canal="evolution")))
    assert "Janela de 24 h" not in evolution
    assert evolution.startswith("# Conversa — Evolution")


def test_ficha_sai_mascarada_e_avisa():
    texto = exportacao.conversa_em_markdown(_retrato())

    assert "## Ficha do cliente" in texto
    assert "- **Nome:** Maria Souza" in texto
    assert "- **CPF:** ***.***.***-67" in texto
    assert "- **Nascimento:** **/**/1990" in texto
    assert "- **UF:** SP" in texto
    assert "o texto das mensagens é o original" in texto


# ------------------------------------------------------------------ mensagens


def test_mensagens_saem_em_ordem_com_autor_hora_e_entrega():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            mensagens=(
                _mensagem("cliente", "quero simular", 1),
                _mensagem("ia", "Boa tarde! Vou te ajudar.", 2, status_entrega="delivered"),
                _mensagem("atendente", "Assumi aqui.", 3, status_entrega="failed"),
            )
        )
    )

    assert "## Mensagens" in texto
    assert "**2025-03-12 09:01 · Cliente**\n\nquero simular" in texto
    assert "**2025-03-12 09:02 · IA · entregue**\n\nBoa tarde! Vou te ajudar." in texto
    assert "**2025-03-12 09:03 · Equipe · falhou**" in texto
    assert texto.index("quero simular") < texto.index("Boa tarde!") < texto.index("Assumi aqui.")


def test_anexo_e_mensagem_sem_texto_ficam_visiveis():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            mensagens=(
                _mensagem(
                    "cliente", "   ", 1, anexos=[{"chave": "s3/x", "mime_type": "audio/ogg"}]
                ),
            )
        )
    )

    assert "_sem texto_" in texto
    assert "_[anexo: audio/ogg]_" in texto


def test_conversa_sem_mensagem_nao_quebra():
    texto = exportacao.conversa_em_markdown(_retrato())

    assert "## Mensagens\n\n_Nenhuma mensagem registrada._" in texto


# ------------------------------------------------------------------ jornada


def test_consentimento_mostra_o_texto_a_resposta_e_a_prova():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            consentimentos=(
                Consentimento(
                    tipo="consulta",
                    texto_mostrado="Autoriza a consulta?\nResponda SIM.",
                    versao="clt-1",
                    resposta_literal="sim, autorizo",
                    wamid="wamid.ABC",
                    cpf="00189004967",
                    criada_em=datetime(2025, 3, 12, 12, 5, tzinfo=UTC),
                ),
            )
        )
    )

    assert "### 2025-03-12 09:05 · consulta" in texto
    assert "> Autoriza a consulta?\n> Responda SIM." in texto
    assert '- **Resposta literal:** "sim, autorizo"' in texto
    assert "- **Versão:** clt-1" in texto
    assert "- **wamid:** wamid.ABC" in texto
    assert "- **CPF:** ***.***.***-67" in texto


def test_granatech_mostra_consulta_eventos_e_proposta():
    consulta = ConsultaGranatech(
        id_externo="887",
        cpf="00189004967",
        status="SUCCESS",
        historico=[
            {"status": "AWAITING_CLIENT_AUTHORIZATION", "recebido_em": "2025-03-12T12:05:00+00:00"},
            {"status": "SUCCESS", "recebido_em": "2025-03-12T12:10:00+00:00"},
        ],
        criada_em=datetime(2025, 3, 12, 12, 5, tzinfo=UTC),
        atualizada_em=datetime(2025, 3, 12, 12, 10, tzinfo=UTC),
    )
    proposta = PropostaGranatech(
        consulta_id=1,
        estado_envio="criada",
        valor_parcela=Decimal("300.00"),
        numero_parcelas=36,
        id_externo="42",
        status="PAYED",
        tipo_notificacao="PAGO",
        historico=[
            {
                "status": "PENDING_FORMALIZATION",
                "tipo_notificacao": "AGUARDANDO_FORMALIZACAO",
                "recebido_em": "2025-03-12T12:20:00+00:00",
            },
            {
                "status": "REPROVED",
                "tipo_notificacao": "REPROVADO",
                "informacoes": "documento ilegível",
                "recebido_em": "2025-03-12T13:20:00+00:00",
            },
        ],
        intencao_em=datetime(2025, 3, 12, 12, 15, tzinfo=UTC),
        atualizada_em=datetime(2025, 3, 12, 13, 20, tzinfo=UTC),
    )

    texto = exportacao.conversa_em_markdown(_retrato(consultas=(consulta,), propostas=(proposta,)))

    assert "### Consulta 887 · SUCCESS" in texto
    assert "- **CPF:** ***.***.***-67" in texto
    assert "  - AWAITING_CLIENT_AUTHORIZATION · 2025-03-12 09:05" in texto
    assert "  - SUCCESS · 2025-03-12 09:10" in texto
    assert "### Proposta 42 · PAYED" in texto
    assert "- **Envio:** criada" in texto
    assert "- **Parcela:** 36 × R$ 300,00" in texto
    assert "  - PENDING_FORMALIZATION · AGUARDANDO_FORMALIZACAO · 2025-03-12 09:20" in texto
    assert "  - REPROVED · REPROVADO · 2025-03-12 10:20 — documento ilegível" in texto


def test_proposta_sem_id_externo_se_identifica_pelo_interno():
    proposta = PropostaGranatech(
        id=9,
        consulta_id=1,
        estado_envio="intencao",
        valor_parcela=Decimal("300.00"),
        numero_parcelas=36,
        historico=[],
        intencao_em=datetime(2025, 3, 12, 12, 15, tzinfo=UTC),
        atualizada_em=datetime(2025, 3, 12, 12, 15, tzinfo=UTC),
    )

    texto = exportacao.conversa_em_markdown(_retrato(propostas=(proposta,)))

    assert "### Proposta interna 9 · intencao" in texto


def test_custo_da_ia_so_aparece_para_gestor():
    turnos = (
        Turno(
            criado_em=datetime(2025, 3, 12, 12, 2, tzinfo=UTC),
            caminho=["roteador", "clt_oferta"],
            status="ok",
            etapa="oferta",
            classificacao={"intencao": "continuar", "publico": "clt", "confianca": 0.87},
            chamadas=[
                {
                    "nome": "consulta_granatech",
                    "status": "200",
                    "latencia_ms": 1240.0,
                    "custo_usd": 0.0012,
                    "tokens_entrada": 900,
                    "tokens_saida": 120,
                }
            ],
            custo_usd=0.0012,
            tokens=1020,
        ),
    )
    do_atendente = exportacao.conversa_em_markdown(_retrato(turnos=turnos))
    do_gestor = exportacao.conversa_em_markdown(_retrato(turnos=turnos, gestor=True))

    assert "### 2025-03-12 09:02 · oferta" in do_atendente
    assert "- **Caminho:** roteador → clt_oferta" in do_atendente
    assert "- **Intenção:** continuar" in do_atendente
    assert "- **Confiança:** 87%" in do_atendente
    assert "  - consulta_granatech · 200 · 1240 ms" in do_atendente
    assert "US$" not in do_atendente
    assert "tok" not in do_atendente

    assert "- **Custo:** US$ 0,0012" in do_gestor
    assert "- **Tokens:** 1.020" in do_gestor
    assert "  - consulta_granatech · 200 · 1240 ms · US$ 0,0012 · 900+120 tok" in do_gestor


def test_custo_minusculo_vira_menor_que_o_menor_visivel():
    turnos = (
        Turno(
            criado_em=datetime(2025, 3, 12, 12, 2, tzinfo=UTC),
            caminho=["roteador"],
            chamadas=[{"nome": "jev", "status": "ok", "custo_usd": 0.00001}],
            custo_usd=0.00001,
            tokens=10,
        ),
    )

    texto = exportacao.conversa_em_markdown(_retrato(turnos=turnos, gestor=True))

    # Como na aba IA: fração de centavo não vira "US$ 0,0000".
    assert "< US$ 0,0001" in texto
    assert "US$ 0,0000" not in texto


def test_campo_sem_valor_nao_vira_linha():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            conversa=_conversa(etapa=None, ultima_entrada_em=None),
            ficha={"nome": None, "dados": {}, "uf": None, "publico": None},
            supervisao={"atencao": [], "motivo_handoff": None},
            turnos=(
                Turno(
                    criado_em=datetime(2025, 3, 12, 12, 2, tzinfo=UTC),
                    caminho=["roteador", "generate_answer"],
                    chamadas=[],
                ),
            ),
        )
    )

    # O painel não mostra campo vazio; o arquivo também não inventa um travessão.
    assert "**Etapa:**" not in texto
    assert "**Nome:**" not in texto
    assert "**UF:**" not in texto
    assert "**Motivo do handoff:**" not in texto
    assert "Cliente escreveu pela última vez em" not in texto
    assert "### 2025-03-12 09:02\n" in texto


def test_secoes_seguem_a_ordem_da_leitura():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            mensagens=(_mensagem("cliente", "oi", 1),),
            consentimentos=(
                Consentimento(
                    tipo="consulta",
                    texto_mostrado="Autoriza?",
                    versao="clt-1",
                    resposta_literal="sim",
                    criada_em=datetime(2025, 3, 12, 12, 5, tzinfo=UTC),
                ),
            ),
        )
    )

    titulos = [linha for linha in texto.splitlines() if linha.startswith(("# ", "## "))]
    assert titulos == [
        "# Conversa — WhatsApp oficial · (11) *****-4321",
        "## Ficha do cliente",
        "## Consentimentos",
        "## Mensagens",
    ]


def test_trilha_avisa_quando_comeca_depois_da_conversa():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            mensagens=(_mensagem("cliente", "oi", 1),),
            turnos=(
                Turno(
                    criado_em=datetime(2025, 3, 12, 15, 0, tzinfo=UTC),
                    caminho=["roteador"],
                    chamadas=[],
                ),
            ),
        )
    )

    # Sem o aviso, o buraco parece conversa sem turno nenhum.
    assert (
        "_A trilha começa em 2025-03-12 12:00; os turnos anteriores não foram gravados._" in texto
    )


def test_trilha_sem_buraco_nao_avisa():
    texto = exportacao.conversa_em_markdown(
        _retrato(
            mensagens=(_mensagem("cliente", "oi", 1),),
            turnos=(
                Turno(
                    criado_em=datetime(2025, 3, 12, 12, 1, tzinfo=UTC),
                    caminho=["roteador"],
                    chamadas=[],
                ),
            ),
        )
    )

    assert "não foram gravados" not in texto
