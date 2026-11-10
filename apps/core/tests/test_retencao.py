"""Retenção do extrato e exclusão (LGPD)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import Fakes
from fastapi.testclient import TestClient

from saturday.agent.service import AgentService
from saturday.schemas import ChatRequest
from saturday.storage.memoria import MemoriaStorage

TZ = ZoneInfo("America/Sao_Paulo")


def test_extrato_com_31_dias_e_limpo_antes_do_turno(
    service_pg: AgentService,
    fakes: Fakes,
    storage: MemoriaStorage,
    monkeypatch: pytest.MonkeyPatch,
    conversa: str,
) -> None:
    """Depois da retenção, o extrato não existe em checkpoint nenhum.

    Os checkpoints antigos guardam os bytes do extrato; limpar só o estado do
    topo não basta. Este teste exige Postgres porque é o único backend onde a
    poda de checkpoints (`prune`) existe.
    """

    agora_fixo = datetime(2026, 10, 8, 12, 0, tzinfo=TZ)
    monkeypatch.setattr("saturday.agent.service.agora", lambda: agora_fixo)
    chave = storage.salvar(b"%PDF-1.4 extrato", mime_type="application/pdf")
    config_antes = service_pg.config(conversa)
    service_pg.graph.update_state(
        config_antes,
        {
            "hiscon": {"ehHiscon": True},
            "portability_result": {"ok": True, "contratos": []},
            "oferta_pendente": True,
            "hiscon_recebido_em": (agora_fixo - timedelta(days=31)).isoformat(),
            "attachments": [{"chave": chave, "mime_type": "application/pdf"}],
        },
    )

    # O checkpoint que guarda o extrato, antes da retenção.
    antes = list(service_pg.checkpointer.list(config_antes))
    assert len(antes) == 1
    id_com_extrato = antes[0].config["configurable"]["checkpoint_id"]

    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    config = service_pg.config(conversa)
    estado = service_pg.graph.get_state(config).values

    assert estado["hiscon"] is None
    assert estado["portability_result"] is None
    assert estado["oferta_pendente"] is False
    assert estado["hiscon_recebido_em"] is None
    assert len(fakes.jev.chamadas) == 1

    # O anexo saiu do storage e o checkpoint que tinha o extrato foi apagado.
    # Os checkpoints que existem agora nasceram depois da limpeza.
    assert storage.existe(chave) is False
    depois = list(service_pg.checkpointer.list(config))
    assert depois
    assert all(item.config["configurable"]["checkpoint_id"] != id_com_extrato for item in depois)


def test_delete_apaga_conversa_e_get_seguinte_retorna_404(client: TestClient) -> None:
    conversa = "apagar"
    criada = client.post("/chat", json={"conversation_id": conversa, "message": "oi"})

    assert criada.status_code == 200
    assert client.delete(f"/conversations/{conversa}").status_code == 204
    assert client.get(f"/conversations/{conversa}").status_code == 404


def test_get_nao_expoe_mensagens_extrato_nem_cliente(client: TestClient) -> None:
    conversa = "sem-vazamento"
    client.post("/chat", json={"conversation_id": conversa, "message": "oi"})

    resposta = client.get(f"/conversations/{conversa}")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "messages" not in corpo
    assert "hiscon" not in corpo
    assert "cliente" not in corpo
