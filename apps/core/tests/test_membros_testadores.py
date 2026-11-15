"""Conversas de membro testador (decisão 0020). Exige Postgres."""

from __future__ import annotations

from sqlalchemy import update

from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import UsuarioPainel
from saturday.dados.sessao import sessao as abrir
from saturday.painel import sessoes
from saturday.schemas import ChatRequest

SENHA = "senha-bem-comprida-1"  # noqa: S105 - senha de teste
TELEFONE = "11987654321"
ORIGEM = OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001")


def _gestor(client, fabrica) -> dict[str, str]:
    with abrir(fabrica) as s:
        sessoes.criar_usuario(s, "gestora@exemplo.test", SENHA, "gestor")
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": "gestora@exemplo.test", "senha": SENHA})
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _membro(fabrica, *, testa: bool, telefone: str | None = TELEFONE) -> str:
    with abrir(fabrica) as s:
        usuario = sessoes.criar_usuario(s, "dev@exemplo.test", SENHA, "atendente", "Dev Teste")
        s.execute(
            update(UsuarioPainel)
            .where(UsuarioPainel.id == usuario.id)
            .values(telefone=telefone, pode_testar_fluxos=testa)
        )
        return str(usuario.id)


def test_conversa_do_telefone_do_membro_testador_ganha_o_selo_e_sai_dos_custos(
    client_pg, service_pg, fabrica, conversa
):
    membro = _membro(fabrica, testa=False)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), ORIGEM)
    service_pg.process_message(
        ChatRequest(conversation_id=f"{conversa}-cliente", message="oi"),
        OrigemCanal(canal="whatsapp", telefone="21912345678", phone_number_id="100000000000001"),
    )
    csrf = _gestor(client_pg, fabrica)

    # Telefone no perfil não basta: precisa da permissão "testar fluxos".
    [sem] = [c for c in client_pg.get("/admin/conversas").json() if c["telefone"].endswith("4321")]
    assert sem["membro"] is None
    turnos_antes = client_pg.get("/admin/custos").json()["total"]["turnos"]

    resposta = client_pg.patch(
        f"/admin/gestao/usuarios/{membro}", json={"pode_testar_fluxos": True}, headers=csrf
    )
    assert resposta.status_code == 204
    linha = next(u for u in client_pg.get("/admin/gestao/usuarios").json() if u["id"] == membro)
    assert linha["pode_testar_fluxos"] is True

    conversas = {c["telefone"][-4:]: c for c in client_pg.get("/admin/conversas").json()}
    assert conversas["4321"]["membro"] == "Dev Teste"
    assert conversas["5678"]["membro"] is None
    execucoes = client_pg.get("/admin/agente/execucoes").json()["execucoes"]
    assert {e["membro"] for e in execucoes} == {"Dev Teste", None}
    # Os turnos do membro saem dos custos; os do cliente ficam.
    assert client_pg.get("/admin/custos").json()["total"]["turnos"] == turnos_antes - 1


def test_membro_desativado_deixa_de_ser_testador(client_pg, service_pg, fabrica, conversa):
    membro = _membro(fabrica, testa=True)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), ORIGEM)
    csrf = _gestor(client_pg, fabrica)
    assert client_pg.get("/admin/conversas").json()[0]["membro"] == "Dev Teste"

    client_pg.post(f"/admin/gestao/usuarios/{membro}/desativar", headers=csrf)
    assert client_pg.get("/admin/conversas").json()[0]["membro"] is None


def test_reiniciar_zera_a_jornada_so_do_membro_testador(service_pg, fabrica, conversa):
    from sqlalchemy import select

    from saturday.agent.textos import MENSAGEM_REINICIADA
    from saturday.dados.modelos import Conversa, Mensagem

    _membro(fabrica, testa=True)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), ORIGEM)
    config = service_pg.config(conversa)
    assert service_pg.estado_atual(config).get("intent")

    resposta = service_pg.process_message(
        ChatRequest(conversation_id=conversa, message=" /Reiniciar ", message_id="wamid.1"), ORIGEM
    )
    assert resposta.answer == MENSAGEM_REINICIADA
    estado = service_pg.estado_atual(config)
    assert not estado.get("intent") and estado.get("message_ids_recentes") == ["wamid.1"]
    with abrir(fabrica) as s:
        conversa_db = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        assert conversa_db.etapa is None
        saidas = s.scalars(
            select(Mensagem.chave_mensagem).where(
                Mensagem.conversa_id == conversa_db.id, Mensagem.direcao == "saida"
            )
        ).all()
        assert "reiniciar" in saidas

    # Webhook repetido devolve a mesma resposta sem reiniciar de novo.
    repetida = service_pg.process_message(
        ChatRequest(conversation_id=conversa, message="/reiniciar", message_id="wamid.1"), ORIGEM
    )
    assert repetida.status == "duplicate"


def test_reiniciar_de_cliente_comum_e_texto_qualquer(service_pg, fabrica, conversa):
    from saturday.agent.textos import MENSAGEM_REINICIADA

    _membro(fabrica, testa=False)
    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), ORIGEM)
    resposta = service_pg.process_message(
        ChatRequest(conversation_id=conversa, message="/reiniciar"), ORIGEM
    )
    assert resposta.answer != MENSAGEM_REINICIADA
    assert service_pg.estado_atual(service_pg.config(conversa)).get("intent")


def test_recontato_de_membro_testador_vence_na_hora(service_pg, fabrica, conversa):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from saturday.dados import recontatos
    from saturday.dados.modelos import Conversa

    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"), ORIGEM)
    amanha = datetime.now(UTC) + timedelta(days=1)
    with abrir(fabrica) as s:
        conversa_id = s.scalar(select(Conversa.id).where(Conversa.conversation_id == conversa))
        cliente = recontatos.agendar(
            s, conversa_id=conversa_id, motivo=recontatos.COTA_ESGOTADA, quando=amanha
        )
        assert cliente.quando == amanha

    _membro(fabrica, testa=True)
    with abrir(fabrica) as s:
        membro = recontatos.agendar(
            s, conversa_id=conversa_id, motivo=recontatos.TEMPO_CASA, quando=amanha
        )
        assert membro.quando <= datetime.now(UTC)
        vencidos = recontatos.vencidos(
            s, motivo=recontatos.TEMPO_CASA, agora=datetime.now(UTC), limite=5
        )
        assert [r.id for r in vencidos] == [membro.id]
