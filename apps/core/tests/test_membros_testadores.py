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
