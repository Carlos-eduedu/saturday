"""Conversas de membro testador (decisão 0020). Exige Postgres."""

from __future__ import annotations

import pytest
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


# ---------------------------------------------------------------- comandos (decisão 0024)


def _dizer(servico, conversa: str, mensagem: str):
    return servico.process_message(ChatRequest(conversation_id=conversa, message=mensagem), ORIGEM)


def _conversa_db(fabrica, conversa: str):
    from sqlalchemy import select

    from saturday.dados.modelos import Conversa

    with abrir(fabrica) as s:
        linha = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        s.expunge(linha)
        return linha


def test_comandos_sem_simulador_e_de_cliente_comum(service_pg, fabrica, conversa):
    from saturday.agent import comandos

    # Cliente comum: comando é texto qualquer, e nada acontece com a conversa.
    assert _dizer(service_pg, conversa, "/humano").answer != comandos.ENVIADA_A_HUMANO
    assert _conversa_db(fabrica, conversa).atendimento == "ia"

    _membro(fabrica, testa=True)
    ajuda = _dizer(service_pg, conversa, "/ajuda").answer
    assert "/ir e /cenario: só com a Granatech simulada" in ajuda
    assert "Atendimento: ia" in _dizer(service_pg, conversa, "/estado").answer
    assert _dizer(service_pg, conversa, "/qualquer").answer == comandos.DESCONHECIDO
    # Regras 3 e 5: sem a Granatech simulada não se pula etapa nem se escolhe resultado.
    for comando in ("/ir oferta", "/ir triagem", "/cenario erro"):
        assert _dizer(service_pg, conversa, comando).answer == comandos.SEM_SIMULADOR
    assert not service_pg.estado_atual(service_pg.config(conversa)).get("clt")


def test_humano_e_devolver_pelo_chat(service_pg, fabrica, conversa):
    import uuid

    from sqlalchemy import select

    from saturday.agent import comandos
    from saturday.agent.textos import MENSAGEM_REINICIADA
    from saturday.dados import atendimento
    from saturday.dados.modelos import Alerta, Conversa

    membro = _membro(fabrica, testa=True)
    _dizer(service_pg, conversa, "oi")
    assert _dizer(service_pg, conversa, "/devolver").answer == comandos.JA_COM_IA

    assert _dizer(service_pg, conversa, "/humano").answer == comandos.ENVIADA_A_HUMANO
    assert _conversa_db(fabrica, conversa).atendimento == "handoff"
    with abrir(fabrica) as s:
        abertos = s.scalars(select(Alerta.tipo).where(Alerta.resolvido_em.is_(None))).all()
        assert abertos == ["handoff"]
    # Mensagem comum fica em silêncio; comando continua respondendo.
    assert _dizer(service_pg, conversa, "tem alguém?").status == "with_human"
    assert _dizer(service_pg, conversa, "/humano").answer == comandos.JA_COM_HUMANO
    assert "Atendimento: handoff" in _dizer(service_pg, conversa, "/estado").answer
    reiniciada = _dizer(service_pg, conversa, "/reiniciar").answer
    assert reiniciada == f"{MENSAGEM_REINICIADA}\n\n{comandos.REINICIADA_COM_HUMANO}"

    assert _dizer(service_pg, conversa, "/devolver").answer == comandos.DEVOLVIDA
    assert _conversa_db(fabrica, conversa).atendimento == "ia"
    with abrir(fabrica) as s:
        assert not s.scalars(select(Alerta).where(Alerta.resolvido_em.is_(None))).all()
    assert _dizer(service_pg, conversa, "oi").status == "answered"

    # Um atendente assumiu a conversa de teste: o membro a tira dele.
    with abrir(fabrica) as s:
        linha = s.scalar(select(Conversa).where(Conversa.conversation_id == conversa))
        atendimento.assumir(s, linha, uuid.UUID(membro))
    assert _dizer(service_pg, conversa, "/devolver").answer == comandos.DEVOLVIDA
    assert _conversa_db(fabrica, conversa).atendimento == "ia"


@pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")
def test_ir_e_cenario_com_a_granatech_simulada(
    service_pg, fabrica, conversa, http_granatech, simulador_granatech, monkeypatch
):
    from dataclasses import replace

    from conftest import settings_granatech
    from sqlalchemy import select

    from saturday.agent import comandos
    from saturday.agent.clt.mensagens import texto
    from saturday.agent.clt.turno import PROVA_DE_TESTE
    from saturday.bancos.granatech.cliente import ClienteGranatech
    from saturday.dados.modelos import Consentimento, ConsultaGranatech
    from saturday.jobs import granatech as jobs_granatech

    _membro(fabrica, testa=True)
    simulado = ClienteGranatech(
        http_granatech, settings_granatech(), fabrica, dormir=lambda _s: None, teste=True
    )
    service_pg.context = replace(
        service_pg.context, fabrica=fabrica, granatech=simulado, granatech_teste=simulado
    )
    eventos: list[dict] = []
    monkeypatch.setattr(simulador_granatech, "entregar", lambda e: eventos.append(e) or 200)

    def clt() -> dict:
        return dict(service_pg.estado_atual(service_pg.config(conversa)).get("clt") or {})

    def aplicar_ultimo() -> None:
        jobs_granatech.aplicar(fabrica, None, {**eventos[-1], "_teste": True}, service_pg)

    assert _dizer(service_pg, conversa, "/ir lua").answer == comandos.LISTA_DE_DESTINOS
    assert _dizer(service_pg, conversa, "/cenario lua").answer == comandos.LISTA_DE_CENARIOS

    # Até o consentimento, só o estado muda: nenhuma prova, nenhuma consulta.
    assert _dizer(service_pg, conversa, "/ir identificacao").answer == texto("pedir_cpf")
    assert clt()["etapa"] == "identificacao"
    assert clt()["dados"] == {"meses_casa": 36, "cnpj": "11222333000181"}
    assert _conversa_db(fabrica, conversa).etapa == "identificacao"
    with abrir(fabrica) as s:
        assert not s.scalars(select(Consentimento)).all()
        assert not s.scalars(select(ConsultaGranatech)).all()

    # O cenário escolhido decide o resultado, que o simulador manda sozinho.
    _dizer(service_pg, conversa, "/cenario sem_margem")
    assert _dizer(service_pg, conversa, "/ir consultando").answer == texto("consultando")
    with abrir(fabrica) as s:
        prova = s.scalars(select(Consentimento)).one()
        assert prova.resposta_literal == f"{PROVA_DE_TESTE} /ir consultando"
        assert s.scalars(select(ConsultaGranatech.teste)).all() == [True]
    assert [e["status"] for e in eventos] == ["NO_MARGIN"]
    aplicar_ultimo()
    assert clt()["etapa"] == "nao_elegivel"
    assert "sem_margem" in _dizer(service_pg, conversa, "/estado").answer

    # `/ir oferta`: consulta nova (não a reaproveitada), sucesso e o primeiro vínculo.
    _dizer(service_pg, conversa, "/reiniciar")
    _dizer(service_pg, conversa, "/ir oferta")
    assert [e["status"] for e in eventos] == ["NO_MARGIN", "SUCCESS"]
    aplicar_ultimo()
    assert clt()["etapa"] == "oferta" and "pular_vinculo" not in clt()
    estado = _dizer(service_pg, conversa, "/estado").answer
    assert "00189004967" not in estado and "Etapa: oferta" in estado

    # Termo pendente: o termo falha, o link vai ao membro e nenhum resultado chega.
    _dizer(service_pg, conversa, "/cenario termo_pendente")
    assert "https://termo.simulador/" in _dizer(service_pg, conversa, "/ir consultando").answer
    assert len(eventos) == 2

    # Com humano, o `/ir` espera a devolução.
    _dizer(service_pg, conversa, "/humano")
    assert _dizer(service_pg, conversa, "/ir triagem").answer == comandos.COM_HUMANO

    # Devolvida, o `/ir` mostra a pergunta da etapa: a resposta seguinte é a ela,
    # não a algo de antes do atendimento (decisão 0033).
    _dizer(service_pg, conversa, "/devolver")
    assert _dizer(service_pg, conversa, "/ir triagem").answer == texto("triagem_carteira")
    assert _dizer(service_pg, conversa, "sim").answer == texto("triagem_tempo_casa")
    _dizer(service_pg, conversa, "/humano")
    _dizer(service_pg, conversa, "/devolver")
    assert _dizer(service_pg, conversa, "/ir consultando").answer.startswith(texto("consultando"))
    assert clt()["etapa"] == "consultando"

    # Regra 12: o cliente da Granatech real nunca manda o cenário.
    real = ClienteGranatech(http_granatech, settings_granatech(), fabrica, dormir=lambda _s: None)
    aberta = real.abrir_consulta("52998224725", "Fulano de Tal", TELEFONE, cenario="erro")
    assert simulador_granatech.CONSULTAS[aberta.id_externo]["cenario"] is None
