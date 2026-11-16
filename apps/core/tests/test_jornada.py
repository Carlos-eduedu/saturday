"""`jornada_do_estado`: o que o painel lê do estado do grafo, com nome."""

from __future__ import annotations

from saturday.agent.service import Jornada, jornada_do_estado


def test_estado_completo_vira_os_campos_da_jornada() -> None:
    oferta = {"valor_parcela": "100.00", "numero_parcelas": 12}
    estado = {
        "publico": "clt",
        "handoff_reason": "pediu_humano",
        "portability_result": {"elegivel": True},
        "clt": {
            "etapa": "oferta",
            "oferta": oferta,
            "proposta": "prop-1",
            "dados": {"email": "cliente@exemplo.test"},
        },
    }

    assert jornada_do_estado(estado) == Jornada(
        ficha={"email": "cliente@exemplo.test"},
        publico="clt",
        motivo_do_handoff="pediu_humano",
        portabilidade={"elegivel": True},
        etapa_clt="oferta",
        oferta=oferta,
        proposta="prop-1",
    )


def test_conversa_sem_checkpoint_tem_jornada_vazia() -> None:
    assert jornada_do_estado({}) == Jornada(
        ficha={},
        publico=None,
        motivo_do_handoff=None,
        portabilidade=None,
        etapa_clt=None,
        oferta=None,
        proposta=None,
    )
