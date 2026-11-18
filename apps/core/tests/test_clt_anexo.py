"""CLT: anexo enviado no meio da jornada (issue 46).

No CLT não há documento para ler: quem manda um anexo recebe de volta a
pergunta da etapa. Na etapa do resumo da proposta o passo também se chama
`sim`, como no pedido de autorização da consulta: o anexo recebe o resumo, não
o pedido da consulta.
"""

from __future__ import annotations

import uuid
from types import ModuleType
from typing import Any

import pytest
from conftest import anexo_fake
from sqlalchemy.orm import Session, sessionmaker
from test_clt_devolucao import (  # noqa: F401 - fixtures
    DADOS_ATE_RESUMO,
    _nada_consultado,
    _nova_fase5,
    _posts_de_proposta,
    _propostas_gravadas,
    _provas,
    nova,
)
from test_clt_jornada import (  # noqa: F401 - fixtures
    ATE_CONSENTIMENTO,
    TELEFONE,
    Jornada,
    _ate_oferta,
    brasilapi,
    fakes_clt,
)

from saturday.agent.clt.mensagens import texto
from saturday.canais.base import OrigemCanal
from saturday.schemas import AgentReply, Attachment, ChatRequest

pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")


def mandar_anexo(jornada: Jornada) -> AgentReply:
    return jornada.servico.process_message(
        ChatRequest(
            conversation_id=jornada.id,
            message_id=f"wamid.{uuid.uuid4().hex}",
            attachments=[Attachment(**anexo_fake())],  # type: ignore[arg-type]
        ),
        OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001"),
    )


def test_anexo_no_pedido_da_consulta_recebe_o_pedido_e_nao_consulta(
    nova: Any,  # noqa: F811
    fabrica: sessionmaker[Session],
    simulador_granatech: ModuleType,
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)

    resposta = mandar_anexo(jornada)

    assert resposta.answer == texto("sem_documento", pergunta=texto("consentimento"))
    assert _provas(jornada) == []
    assert _nada_consultado(fabrica, simulador_granatech)


def test_anexo_no_resumo_da_proposta_recebe_o_resumo_e_nao_o_pedido_da_consulta(
    nova: Any,  # noqa: F811
    fabrica: sessionmaker[Session],
    simulador_granatech: ModuleType,
) -> None:
    jornada = nova()
    _ate_oferta(jornada)
    resumo = jornada.roteiro(*DADOS_ATE_RESUMO).answer
    assert resumo.startswith("Confira o resumo da proposta")

    resposta = mandar_anexo(jornada)

    assert texto("consentimento") not in resposta.answer
    assert (resposta.status, resposta.answer) == ("answered", resumo)
    assert [tipo for tipo, _, _ in _provas(jornada)] == ["consulta"]
    assert _propostas_gravadas(fabrica) == 0
    assert _posts_de_proposta(simulador_granatech) == 0

    # A prova guarda o que o cliente viu por último; regra 4: um POST só.
    assert jornada.falar("SIM").answer == texto("proposta_enviada")
    assert _provas(jornada)[-1] == ("proposta", resumo, "SIM")
    assert _propostas_gravadas(fabrica) == 1
    assert _posts_de_proposta(simulador_granatech) == 1
