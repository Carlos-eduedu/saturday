"""API do painel (`/admin/*`): aceite da Fase 3. Exige Postgres."""

from __future__ import annotations

import uuid

import pytest
from conftest import resultado_jev
from sqlalchemy import func, select, update

from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import Auditoria, Conversa, Mensagem, Outbox
from saturday.dados.sessao import sessao as abrir
from saturday.painel import acoes, sessoes
from saturday.schemas import ChatRequest

SENHA = "senha-bem-comprida-1"
TELEFONE = "11987654321"
WHATSAPP = OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001")


def _criar(fabrica, email, perfil="atendente"):
    with abrir(fabrica) as s:
        return str(sessoes.criar_usuario(s, email, SENHA, perfil).id)


def _entrar(client, email):
    client.cookies.clear()
    resposta = client.post("/admin/login", json={"email": email, "senha": SENHA})
    assert resposta.status_code == 200
    return {"X-CSRF-Token": resposta.json()["csrf"]}


def _cliente_escreve(service, conversation_id, texto):
    return service.process_message(
        ChatRequest(conversation_id=conversation_id, message=texto), WHATSAPP
    )


def _conversa_id(fabrica, conversation_id):
    with abrir(fabrica) as s:
        return str(s.scalar(select(Conversa.id).where(Conversa.conversation_id == conversation_id)))


def _saidas(fabrica):
    with abrir(fabrica) as s:
        return [
            (m.autor, m.conteudo)
            for m in s.scalars(
                select(Mensagem).where(Mensagem.direcao == "saida").order_by(Mensagem.id)
            )
        ]


@pytest.fixture
def ana(fabrica):
    return _criar(fabrica, "ana@exemplo.test")


# ------------------------------------------------------------------ sessão


def test_login_errado_e_inexistente_tem_a_mesma_resposta(client_pg, ana):
    errada = client_pg.post("/admin/login", json={"email": "ana@exemplo.test", "senha": "x"})
    inexistente = client_pg.post("/admin/login", json={"email": "zz@exemplo.test", "senha": "x"})
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()


def test_cookie_da_sessao_sai_com_as_flags(client_pg, ana):
    resposta = client_pg.post("/admin/login", json={"email": "ana@exemplo.test", "senha": SENHA})
    cookie = resposta.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/admin" in cookie


def test_cookie_e_secure_fora_de_dev(client_pg, ana, settings):
    settings.environment = "homolog"
    resposta = client_pg.post("/admin/login", json={"email": "ana@exemplo.test", "senha": SENHA})
    assert "secure" in resposta.headers["set-cookie"].lower()


def test_sem_sessao_401_e_sem_csrf_403(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    assert client_pg.get("/admin/conversas").status_code == 401

    csrf = _entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir").status_code == 403
    errado = {"X-CSRF-Token": "0" * 64}
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=errado).status_code == 403
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204


def test_logout_encerra_a_sessao(client_pg, ana):
    csrf = _entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post("/admin/logout", headers=csrf).status_code == 204
    assert client_pg.get("/admin/eu").status_code == 401


# ------------------------------------------------------------------ aceite 1


def test_atendente_assume_responde_e_ia_cala_ate_devolver(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")

    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204
    enviada = client_pg.post(
        f"/admin/conversas/{alvo}/mensagens", headers=csrf, json={"texto": "Oi, sou a Ana."}
    )
    assert enviada.status_code == 201
    with abrir(fabrica) as s:
        linha = s.scalars(select(Outbox).order_by(Outbox.id.desc())).first()
        assert linha is not None
        assert linha.payload["answer"] == "Oi, sou a Ana."
        assert linha.payload["mensagem_id"] == enviada.json()["mensagem_id"]

    chamadas_antes = len(fakes.jev.chamadas)
    saidas_antes = _saidas(fabrica)
    assert _cliente_escreve(service_pg, conversa, "e aí?").status == "with_human"
    assert len(fakes.jev.chamadas) == chamadas_antes
    assert _saidas(fabrica) == saidas_antes
    assert saidas_antes[-1] == ("atendente", "Oi, sou a Ana.")

    assert client_pg.post(f"/admin/conversas/{alvo}/devolver", headers=csrf).status_code == 204
    fakes.jev.resultado = resultado_jev()
    assert _cliente_escreve(service_pg, conversa, "voltei").status == "answered"
    assert _saidas(fabrica)[-1][0] == "ia"

    with abrir(fabrica) as s:
        acoes = [a.acao for a in s.scalars(select(Auditoria).order_by(Auditoria.id))]
    assert acoes == ["assumir", "enviar_mensagem", "devolver"]


def test_so_o_dono_envia(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.post(
        f"/admin/conversas/{alvo}/mensagens", headers=csrf, json={"texto": "oi"}
    )
    assert resposta.status_code == 409


def test_janela_fechada_so_aceita_modelo(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    with abrir(fabrica) as s:
        conversa_db = s.get(Conversa, uuid.UUID(alvo))
        assert conversa_db is not None
        conversa_db.ultima_entrada_em = conversa_db.criada_em.replace(year=2020)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)

    texto = client_pg.post(f"/admin/conversas/{alvo}/mensagens", headers=csrf, json={"texto": "oi"})
    assert texto.status_code == 409
    marketing = client_pg.post(
        f"/admin/conversas/{alvo}/mensagens",
        headers=csrf,
        json={"modelo": "recontato_tempo_casa"},
    )
    assert marketing.status_code == 422
    modelo = client_pg.post(
        f"/admin/conversas/{alvo}/mensagens",
        headers=csrf,
        json={"modelo": "atualizacao_pedido"},
    )
    assert modelo.status_code == 201
    with abrir(fabrica) as s:
        linha = s.scalars(select(Outbox).order_by(Outbox.id.desc())).first()
        assert linha is not None
        assert linha.payload["modelo"] == "atualizacao_pedido"


def test_transferir_e_tomar_de_outro(client_pg, service_pg, fabrica, ana, conversa):
    bia = _criar(fabrica, "bia@exemplo.test")
    _criar(fabrica, "gestor@exemplo.test", "gestor")
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)

    csrf = _entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    transferida = client_pg.post(
        f"/admin/conversas/{alvo}/transferir", headers=csrf, json={"usuario_id": bia}
    )
    assert transferida.status_code == 204

    # Ana não é mais a dona: não toma de volta nem devolve.
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 403
    assert client_pg.post(f"/admin/conversas/{alvo}/devolver", headers=csrf).status_code == 403

    csrf = _entrar(client_pg, "gestor@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204
    detalhe = client_pg.get(f"/admin/conversas/{alvo}").json()
    assert detalhe["atendimento"] == "assumida"
    assert detalhe["atendente_id"] != bia


def _atendimento(client, alvo):
    detalhe = client.get(f"/admin/conversas/{alvo}").json()
    return detalhe["atendimento"], detalhe["atendente_id"]


def test_desfazer_devolve_o_estado_de_antes(client_pg, service_pg, fabrica, ana, conversa):
    bia = _criar(fabrica, "bia@exemplo.test")
    _criar(fabrica, "gestor@exemplo.test", "gestor")
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    with abrir(fabrica) as s:
        s.get(Conversa, uuid.UUID(alvo)).atendimento = "handoff"

    # Assumir um handoff e desfazer volta ao handoff, não à IA.
    csrf = _entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert _atendimento(client_pg, alvo) == ("handoff", None)
    # Desfazer não se desfaz.
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 409

    # Devolver e desfazer devolve a conversa a quem estava com ela.
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    client_pg.post(f"/admin/conversas/{alvo}/devolver", headers=csrf)
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert _atendimento(client_pg, alvo) == ("assumida", ana)

    # O gestor toma a conversa da Ana e desfaz: ela volta para a Ana.
    csrf = _entrar(client_pg, "gestor@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert _atendimento(client_pg, alvo) == ("assumida", ana)

    # Só desfaz quem agiu, e só enquanto nada mais mexeu no atendimento.
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    csrf_ana = _entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf_ana).status_code == 409
    csrf = _entrar(client_pg, "gestor@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/transferir", headers=csrf, json={"usuario_id": bia})
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 409


def test_desfazer_vence_com_o_prazo(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    with abrir(fabrica) as s:
        s.execute(
            update(Auditoria)
            .where(Auditoria.acao == "assumir")
            .values(criada_em=func.now() - acoes.PRAZO_DESFAZER * 2)
        )

    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 409
    assert _atendimento(client_pg, alvo) == ("assumida", ana)


def test_inbox_filtra_por_fila_e_marca_lida(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")

    [item] = client_pg.get("/admin/conversas", params={"fila": "ia"}).json()
    assert item["id"] == alvo
    assert item["nao_lida"] is True
    assert item["janela_aberta"] is True
    assert item["telefone"] == "(11) *****-4321"
    assert client_pg.get("/admin/conversas", params={"fila": "minhas"}).json() == []

    detalhe = client_pg.get(f"/admin/conversas/{alvo}").json()
    assert detalhe["ultima_mensagem"]["autor"] in {"ia", "cliente"}
    assert "motivo_handoff" in detalhe and "atencao" in detalhe
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    [item] = client_pg.get("/admin/conversas", params={"fila": "minhas"}).json()
    assert item["nao_lida"] is False
    assert client_pg.get("/admin/conversas", params={"busca": "4321"}).json()[0]["id"] == alvo


# ------------------------------------------------------------------ aceite 2


def test_ficha_mostra_os_dados_do_ramo_clt(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    dados = {
        "cpf": "00189004967",
        "nome": "Maria da Silva",
        "nascimento": "1990-05-15",
        "email": "maria@exemplo.test",
    }
    service_pg.graph.update_state(service_pg.config(conversa), {"clt": {"dados": dados}})
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")

    ficha = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    assert ficha["nome"] == "Maria da Silva"
    assert ficha["dados"]["cpf"] == "***.***.***-67"
    assert ficha["dados"]["data_nascimento"] == "**/**/1990"
    assert ficha["dados"]["email"] == "m***@exemplo.test"
    revelado = client_pg.post(
        f"/admin/conversas/{alvo}/revelar", headers=csrf, json={"campo": "email"}
    )
    assert revelado.json() == {"campo": "email", "valor": "maria@exemplo.test"}


def test_revelar_cpf_grava_auditoria(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    service_pg.graph.update_state(service_pg.config(conversa), {"cliente": {"cpf": "00189004967"}})
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")

    ficha = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    assert ficha["dados"]["cpf"] == "***.***.***-67"
    with abrir(fabrica) as s:
        assert s.scalars(select(Auditoria)).all() == []

    revelado = client_pg.post(
        f"/admin/conversas/{alvo}/revelar", headers=csrf, json={"campo": "cpf"}
    )
    assert revelado.json() == {"campo": "cpf", "valor": "00189004967"}
    with abrir(fabrica) as s:
        [registro] = s.scalars(select(Auditoria)).all()
        assert registro.acao == "revelar:cpf"
        assert registro.alvo == alvo
        assert str(registro.usuario_id) == ana


def test_revelar_exige_csrf(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    _entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.post(f"/admin/conversas/{alvo}/revelar", json={"campo": "telefone"})
    assert resposta.status_code == 403


# ------------------------------------------------------------------ exportação


def test_exportar_devolve_a_conversa_em_markdown(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi, quero simular")
    alvo = _conversa_id(fabrica, conversa)
    _entrar(client_pg, "ana@exemplo.test")

    resposta = client_pg.get(f"/admin/conversas/{alvo}/exportar")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/markdown")
    assert resposta.headers["content-disposition"] == f'attachment; filename="conversa-{alvo}.md"'
    assert resposta.headers["cache-control"] == "private, no-store"
    assert resposta.text.startswith("# Conversa — WhatsApp oficial")
    assert "## Mensagens" in resposta.text
    assert "oi, quero simular" in resposta.text
    # O arquivo leva a conversa para fora do painel: fica registrado quem levou.
    with abrir(fabrica) as s:
        assert [a.acao for a in s.scalars(select(Auditoria))] == ["exportar"]


def test_exportar_exige_sessao(client_pg, service_pg, fabrica, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    client_pg.cookies.clear()
    assert client_pg.get(f"/admin/conversas/{alvo}/exportar").status_code == 401


# ------------------------------------------------------------------ alertas, cota, mídia


def test_alerta_de_handoff_e_resolvido_com_auditoria(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    _cliente_escreve(service_pg, conversa, "humano")
    csrf = _entrar(client_pg, "ana@exemplo.test")

    [alerta] = client_pg.get("/admin/alertas").json()
    assert alerta["tipo"] == "handoff"
    assert (
        client_pg.post(f"/admin/alertas/{alerta['id']}/resolver", headers=csrf).status_code == 204
    )
    assert client_pg.get("/admin/alertas").json() == []
    with abrir(fabrica) as s:
        assert [a.acao for a in s.scalars(select(Auditoria))] == ["resolver_alerta"]


def test_cota_zerada_mostra_os_tetos(client_pg, ana):
    _entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get("/admin/cota").json() == {
        "mes": {"usadas": 0, "teto": 500},
        "dia": {"usadas": 0, "teto": 20},
    }


def test_midia_passa_pela_api_com_sessao(client_pg, service_pg, fabrica, storage, ana, conversa):
    chave = storage.salvar(b"%PDF-1.4", mime_type="application/pdf")
    _cliente_escreve(service_pg, conversa, "oi")
    with abrir(fabrica) as s:
        mensagem = s.scalars(select(Mensagem).where(Mensagem.direcao == "entrada")).first()
        assert mensagem is not None
        mensagem.anexos = [{"chave": chave, "mime_type": "application/pdf"}]
        mensagem_id = mensagem.id

    assert client_pg.get(f"/admin/midia/{mensagem_id}/0").status_code == 401
    _entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.get(f"/admin/midia/{mensagem_id}/0")
    assert resposta.status_code == 200
    assert resposta.content == b"%PDF-1.4"
    assert resposta.headers["content-type"] == "application/pdf"
    assert client_pg.get(f"/admin/midia/{mensagem_id}/1").status_code == 404
