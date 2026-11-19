"""API do painel (`/admin/*`): aceite da Fase 3. Exige Postgres."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from conftest import entrar, resultado_jev
from sqlalchemy import func, select, update

from saturday.canais.base import OrigemCanal
from saturday.dados import repositorios
from saturday.dados.modelos import (
    Alerta,
    Auditoria,
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Mensagem,
    Outbox,
    PropostaGranatech,
)
from saturday.dados.sessao import sessao as abrir
from saturday.painel import acoes, sessoes
from saturday.painel.canal import MODELOS_DO_PAINEL
from saturday.schemas import ChatRequest
from saturday.web.api.admin import abre_no_navegador

SENHA = "senha-bem-comprida-1"
TELEFONE = "11987654321"
WHATSAPP = OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001")


def _criar(fabrica, email, perfil="atendente"):
    with abrir(fabrica) as s:
        return str(sessoes.criar_usuario(s, email, SENHA, perfil).id)


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

    csrf = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir").status_code == 403
    errado = {"X-CSRF-Token": "0" * 64}
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=errado).status_code == 403
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204


def test_logout_encerra_a_sessao(client_pg, ana):
    csrf = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post("/admin/logout", headers=csrf).status_code == 204
    assert client_pg.get("/admin/eu").status_code == 401


# ------------------------------------------------------------------ aceite 1


def test_atendente_assume_responde_e_ia_cala_ate_devolver(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")

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
    csrf = entrar(client_pg, "ana@exemplo.test")
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
    csrf = entrar(client_pg, "ana@exemplo.test")
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

    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    transferida = client_pg.post(
        f"/admin/conversas/{alvo}/transferir", headers=csrf, json={"usuario_id": bia}
    )
    assert transferida.status_code == 204

    # Ana não é mais a dona: não toma de volta nem devolve.
    assert client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 403
    assert client_pg.post(f"/admin/conversas/{alvo}/devolver", headers=csrf).status_code == 403

    csrf = entrar(client_pg, "gestor@exemplo.test")
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
    csrf = entrar(client_pg, "ana@exemplo.test")
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
    csrf = entrar(client_pg, "gestor@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert _atendimento(client_pg, alvo) == ("assumida", ana)

    # Só desfaz quem agiu, e só enquanto nada mais mexeu no atendimento.
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    csrf_ana = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf_ana).status_code == 409
    csrf = entrar(client_pg, "gestor@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/transferir", headers=csrf, json={"usuario_id": bia})
    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 409


def test_desfazer_vence_com_o_prazo(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    with abrir(fabrica) as s:
        s.execute(
            update(Auditoria)
            .where(Auditoria.acao == "assumir")
            .values(criada_em=func.now() - acoes.PRAZO_DESFAZER * 2)
        )

    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 409
    assert _atendimento(client_pg, alvo) == ("assumida", ana)


def test_instancia_apagada_recusa_o_envio(client_pg, service_pg, fabrica, ana, conversa):
    """Caso de prod (19/11): o envio pela instância apagada dava 404 e se perdia."""

    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    with abrir(fabrica) as s:
        s.execute(
            update(Conversa)
            .where(Conversa.id == uuid.UUID(alvo))
            .values(canal="evolution", phone_number_id=None)
        )
    with abrir(fabrica) as s:
        na_fila = s.scalar(select(func.count()).select_from(Outbox))

    resposta = client_pg.post(
        f"/admin/conversas/{alvo}/mensagens", headers=csrf, json={"texto": "oi"}
    )

    assert resposta.status_code == 409
    assert "instância desta conversa foi apagada" in resposta.json()["detail"]
    with abrir(fabrica) as s:
        assert s.scalar(select(func.count()).select_from(Outbox)) == na_fila
    item = client_pg.get(f"/admin/conversas/{alvo}").json()
    assert (item["envia"], item["instancia_apagada"]) == (False, True)


def test_conversa_do_chat_nao_tem_janela_nem_envio(client_pg, service_pg, ana, conversa):
    """Janela é da Meta: no canal `chat` o painel não mostra o selo nem envia."""

    service_pg.process_message(ChatRequest(conversation_id=conversa, message="oi"))
    entrar(client_pg, "ana@exemplo.test")

    [item] = client_pg.get("/admin/conversas").json()
    assert (item["envia"], item["janela"], item["modelos"]) == (False, None, [])


def test_inbox_filtra_por_fila_e_marca_lida(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")

    [item] = client_pg.get("/admin/conversas", params={"fila": "ia"}).json()
    assert item["id"] == alvo
    assert item["nao_lida"] is True
    assert (item["envia"], item["janela"]) == (True, "aberta")
    assert item["modelos"] == list(MODELOS_DO_PAINEL)
    assert item["telefone"] == "(11) *****-4321"
    assert client_pg.get("/admin/conversas", params={"fila": "minhas"}).json() == []

    detalhe = client_pg.get(f"/admin/conversas/{alvo}").json()
    assert detalhe["ultima_mensagem"]["autor"] in {"ia", "cliente"}
    assert "motivo_handoff" in detalhe and "atencao" in detalhe
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    [item] = client_pg.get("/admin/conversas", params={"fila": "minhas"}).json()
    assert item["nao_lida"] is False
    assert client_pg.get("/admin/conversas", params={"busca": "4321"}).json()[0]["id"] == alvo


def test_contagens_das_filas_e_a_fila_minhas(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    assert client_pg.get("/admin/conversas/contagens").status_code == 401
    csrf = entrar(client_pg, "ana@exemplo.test")

    contagens = client_pg.get("/admin/conversas/contagens").json()
    assert contagens == {
        "todas": 1,
        "ia": 1,
        "handoff": 0,
        "assumida": 0,
        "minhas": 0,
        "atencao": 0,
    }

    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    contagens = client_pg.get("/admin/conversas/contagens").json()
    assert (contagens["ia"], contagens["assumida"], contagens["minhas"]) == (0, 1, 1)
    _criar(fabrica, "bia@exemplo.test")
    entrar(client_pg, "bia@exemplo.test")
    assert client_pg.get("/admin/conversas/contagens").json()["minhas"] == 0


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
    csrf = entrar(client_pg, "ana@exemplo.test")

    ficha = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    assert ficha["nome"] == "Maria da Silva"
    assert ficha["dados"]["cpf"] == "***.***.***-67"
    assert ficha["dados"]["data_nascimento"] == "**/**/1990"
    assert ficha["dados"]["email"] == "m***@exemplo.test"
    revelado = client_pg.post(
        f"/admin/conversas/{alvo}/revelar", headers=csrf, json={"campo": "email"}
    )
    assert revelado.json() == {"campo": "email", "valor": "maria@exemplo.test"}


def test_ficha_mostra_oferta_proposta_e_provas(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    entrar(client_pg, "ana@exemplo.test")

    vazia = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    assert (vazia["oferta"], vazia["proposta"], vazia["consentimentos"]) == (None, None, [])

    oferta = {
        "liberado": "4619.53",
        "valor_parcela": "300.00",
        "numero_parcelas": 36,
        "taxa_mensal": "4.00",
        "cet_mensal": "4.9848",
        "valor_seguro": "503.32",
        "seguro_aplicado": True,
        "limitado_ao_teto": False,
        "id_produto": "17",
        "id_margem": "9",
    }
    service_pg.graph.update_state(service_pg.config(conversa), {"clt": {"oferta": oferta}})
    with abrir(fabrica) as s:
        s.add(
            Consentimento(
                conversa_id=uuid.UUID(alvo),
                tipo="consulta",
                texto_mostrado="Você autoriza? Responda SIM.",
                versao="v1",
                resposta_literal="SIM",
                cpf="00189004967",
            )
        )
        consulta = ConsultaGranatech(
            id_externo="c-1", cpf="00189004967", conversa_id=uuid.UUID(alvo), status="SUCCESS"
        )
        s.add(consulta)
        s.flush()
        s.add(
            PropostaGranatech(
                consulta_id=consulta.id,
                conversa_id=uuid.UUID(alvo),
                estado_envio="criada",
                valor_parcela=Decimal("300.00"),
                numero_parcelas=36,
                status="PENDING_FORMALIZATION",
                condicoes=oferta,
            )
        )

    ficha = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    # Só valores: os IDs do banco e o CPF da prova não saem na ficha.
    assert ficha["oferta"] == {k: v for k, v in oferta.items() if not k.startswith("id_")}
    assert ficha["proposta"]["status"] == "PENDING_FORMALIZATION"
    assert ficha["proposta"]["difere_da_oferta"] is False
    assert [(p["tipo"], p["resposta_literal"]) for p in ficha["consentimentos"]] == [
        ("consulta", "SIM")
    ]
    assert "cpf" not in ficha["consentimentos"][0]

    # A IA refez a simulação com outra parcela: a proposta do banco não acompanha.
    service_pg.graph.update_state(
        service_pg.config(conversa), {"clt": {"oferta": {**oferta, "valor_parcela": "250.00"}}}
    )
    ficha = client_pg.get(f"/admin/conversas/{alvo}/ficha").json()
    assert ficha["proposta"]["difere_da_oferta"] is True
    # As condições guardadas na proposta não mudam com a nova simulação, e saem sem IDs.
    assert ficha["proposta"]["condicoes"] == {
        k: v for k, v in oferta.items() if not k.startswith("id_")
    }


def test_revelar_cpf_grava_auditoria(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    service_pg.graph.update_state(service_pg.config(conversa), {"cliente": {"cpf": "00189004967"}})
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")

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
    entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.post(f"/admin/conversas/{alvo}/revelar", json={"campo": "telefone"})
    assert resposta.status_code == 403


# ------------------------------------------------------------------ exportação


def test_exportar_devolve_a_conversa_em_markdown(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi, quero simular")
    alvo = _conversa_id(fabrica, conversa)
    entrar(client_pg, "ana@exemplo.test")

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


def _alertas_abertos(fabrica):
    with abrir(fabrica) as s:
        return sorted(
            (a.tipo, a.id) for a in s.scalars(select(Alerta).where(Alerta.resolvido_em.is_(None)))
        )


def _abrir_alerta(fabrica, alvo, tipo):
    with abrir(fabrica) as s:
        return repositorios.abrir_alerta(s, tipo, conversa_id=uuid.UUID(alvo)).id


def test_assumir_resolve_o_handoff_e_desfazer_reabre(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    _cliente_escreve(service_pg, conversa, "humano")
    alvo = _conversa_id(fabrica, conversa)
    [(tipo, alerta_id)] = _alertas_abertos(fabrica)
    assert tipo == "handoff"
    evento = _abrir_alerta(fabrica, alvo, "evento_com_humano")

    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    assert _alertas_abertos(fabrica) == [("evento_com_humano", evento)]
    with abrir(fabrica) as s:
        assumiu = s.scalars(select(Auditoria).where(Auditoria.acao == "assumir")).one()
        assert assumiu.detalhe["alertas"] == [alerta_id]
        assert s.get(Alerta, alerta_id).resolvido_por == uuid.UUID(ana)

    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert _alertas_abertos(fabrica) == sorted(
        [("handoff", alerta_id), ("evento_com_humano", evento)]
    )
    with abrir(fabrica) as s:
        desfez = s.scalars(select(Auditoria).where(Auditoria.acao == "desfazer")).one()
        assert desfez.detalhe["alertas_reabertos"] == [alerta_id]
        assert s.get(Alerta, alerta_id).resolvido_por is None


def test_desfazer_de_auditoria_antiga_abre_o_alerta_de_handoff(
    client_pg, service_pg, fabrica, ana, conversa
):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    with abrir(fabrica) as s:
        s.get(Conversa, uuid.UUID(alvo)).atendimento = "handoff"
    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    with abrir(fabrica) as s:
        # Linha gravada antes da decisão 0018: sem a lista de alertas.
        s.execute(
            update(Auditoria)
            .where(Auditoria.acao == "assumir")
            .values(detalhe={"antes": "handoff", "de": None})
        )

    assert client_pg.post(f"/admin/conversas/{alvo}/desfazer", headers=csrf).status_code == 204
    assert [tipo for tipo, _ in _alertas_abertos(fabrica)] == ["handoff"]


def test_devolver_resolve_sem_resposta_e_transferir_nao_mexe(
    client_pg, service_pg, fabrica, ana, conversa
):
    bia = _criar(fabrica, "bia@exemplo.test")
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    csrf = entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    sem_resposta = _abrir_alerta(fabrica, alvo, "sem_resposta")
    handoff = _abrir_alerta(fabrica, alvo, "handoff")

    client_pg.post(f"/admin/conversas/{alvo}/transferir", headers=csrf, json={"usuario_id": bia})
    assert _alertas_abertos(fabrica) == sorted(
        [("sem_resposta", sem_resposta), ("handoff", handoff)]
    )

    csrf = entrar(client_pg, "bia@exemplo.test")
    assert client_pg.post(f"/admin/conversas/{alvo}/devolver", headers=csrf).status_code == 204
    assert _alertas_abertos(fabrica) == []


def test_alerta_de_handoff_e_resolvido_com_auditoria(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    fakes.jev.resultado = resultado_jev("humano", 0.95)
    _cliente_escreve(service_pg, conversa, "humano")
    csrf = entrar(client_pg, "ana@exemplo.test")

    [alerta] = client_pg.get("/admin/alertas").json()
    assert alerta["tipo"] == "handoff"
    assert (
        client_pg.post(f"/admin/alertas/{alerta['id']}/resolver", headers=csrf).status_code == 204
    )
    assert client_pg.get("/admin/alertas").json() == []
    with abrir(fabrica) as s:
        assert [a.acao for a in s.scalars(select(Auditoria))] == ["resolver_alerta"]


def test_cota_zerada_mostra_os_tetos(client_pg, ana):
    entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get("/admin/cota").json() == {
        "mes": {"usadas": 0, "teto": 500},
        "dia": {"usadas": 0, "teto": 20},
    }


def test_cota_por_dia_traz_so_o_mes_corrente(client_pg, fabrica, ana):
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from saturday.dados.modelos import Cota
    from saturday.settings import TZ_OPERACAO

    hoje = datetime.now(ZoneInfo(TZ_OPERACAO)).date()
    inicio = date(hoje.year, hoje.month, 1)
    with abrir(fabrica) as s:
        s.add_all(
            [
                Cota(parceiro="granatech", dia=hoje, usadas=3),
                Cota(parceiro="granatech", dia=inicio - timedelta(days=1), usadas=9),
                Cota(parceiro="outro", dia=hoje, usadas=5),
            ]
        )
    entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.get("/admin/cota/dias").json()
    assert resposta["de"] == inicio.isoformat() and resposta["ate"] == hoje.isoformat()
    assert resposta["teto_diario"] == 20 and resposta["teto_mensal"] == 500
    assert resposta["dias"] == [{"dia": hoje.isoformat(), "usadas": 3}]


def test_produtos_trazem_as_regras_vigentes(client_pg, ana):
    assert client_pg.get("/admin/produtos").status_code == 401
    entrar(client_pg, "ana@exemplo.test")
    inss, novo, clt = client_pg.get("/admin/produtos").json()
    itens = {i["rotulo"]: i["valor"] for p in (inss, clt) for g in p["grupos"] for i in g["itens"]}
    assert [p["banco"]["id"] for p in (inss, novo, clt)] == ["c6", "c6", "granatech"]
    # O contrato que nasce da portabilidade não é o produto "contrato novo".
    assert [g["titulo"] for g in inss["grupos"]][-1] == "Contrato no C6 após a portabilidade"
    assert (novo["id"], novo["nome"]) == ("contrato-novo-inss", "Contrato novo INSS (C6)")
    do_novo = {i["rotulo"]: i["valor"] for g in novo["grupos"] for i in g["itens"]}
    assert do_novo["Idade"] == "21 a 79 anos"
    assert do_novo["Margem livre mínima"] == "R$ 20,00"
    assert do_novo["Parcela pedida"] == "99% da margem livre"
    assert do_novo["Valor mínimo na conta"] == "R$ 1.000,00"
    assert do_novo["Taxa máxima"] == "1,85% ao mês"
    assert do_novo["Até 71 anos"] == "108 parcelas, sem teto"
    assert do_novo["73 anos"] == "84 parcelas, sem teto"
    assert do_novo["74 anos"] == "72 parcelas, até R$ 35.000,00"
    assert do_novo["79 anos"] == "12 parcelas, até R$ 5.000,00"
    assert itens["Idade"] == "21 a 73 anos"
    assert "Nubank" not in itens["Não porta"] and "Daycoval" in itens["Não porta"]
    assert itens["Sobra mínima"] == "R$ 50,00 por contrato"
    assert itens["Valor liberado máximo"] == "R$ 6.999,00"
    assert itens["Cota mensal"] == "500 consultas"


def test_midia_passa_pela_api_com_sessao(client_pg, service_pg, fabrica, storage, ana, conversa):
    chave = storage.salvar(b"%PDF-1.4", mime_type="application/pdf")
    _cliente_escreve(service_pg, conversa, "oi")
    with abrir(fabrica) as s:
        mensagem = s.scalars(select(Mensagem).where(Mensagem.direcao == "entrada")).first()
        assert mensagem is not None
        mensagem.anexos = [{"chave": chave, "mime_type": "application/pdf"}]
        mensagem_id = mensagem.id

    assert client_pg.get(f"/admin/midia/{mensagem_id}/0").status_code == 401
    entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.get(f"/admin/midia/{mensagem_id}/0")
    assert resposta.status_code == 200
    assert resposta.content == b"%PDF-1.4"
    assert resposta.headers["content-type"] == "application/pdf"
    assert "content-disposition" not in resposta.headers
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert client_pg.get(f"/admin/midia/{mensagem_id}/1").status_code == 404


@pytest.mark.parametrize(
    "mime",
    ["text/html", "TEXT/HTML; charset=utf-8", "image/svg+xml", "application/xhtml+xml", ""],
)
def test_midia_fora_da_lista_so_baixa(client_pg, service_pg, fabrica, storage, ana, conversa, mime):
    """O tipo é o que o cliente declarou: HTML ou SVG não pode abrir no painel."""

    chave = storage.salvar(b"<script>alert(1)</script>", mime_type="text/html")
    _cliente_escreve(service_pg, conversa, "oi")
    with abrir(fabrica) as s:
        mensagem = s.scalars(select(Mensagem).where(Mensagem.direcao == "entrada")).first()
        assert mensagem is not None
        mensagem.anexos = [{"chave": chave, "mime_type": mime}]
        mensagem_id = mensagem.id

    entrar(client_pg, "ana@exemplo.test")
    resposta = client_pg.get(f"/admin/midia/{mensagem_id}/0")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/octet-stream"
    assert resposta.headers["content-disposition"] == "attachment"
    assert resposta.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("mime", "abre"),
    [
        ("image/jpeg", True),
        ("IMAGE/PNG", True),
        ("audio/ogg; codecs=opus", True),
        ("video/mp4", True),
        ("application/pdf", True),
        ("image/svg+xml", False),
        ("text/html", False),
        ("application/octet-stream", False),
        ("", False),
    ],
)
def test_abre_no_navegador(mime, abre):
    assert abre_no_navegador(mime) is abre


def test_historico_traz_o_turno_e_a_chave_da_fala(
    client_pg, service_pg, fakes, fabrica, ana, conversa
):
    fakes.jev.resultado = resultado_jev(intent="saudacao")
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    entrar(client_pg, "ana@exemplo.test")

    mensagens = client_pg.get(f"/admin/conversas/{alvo}").json()["mensagens"]
    entrada, saida = mensagens
    assert entrada["turno_id"] is None and entrada["chave_mensagem"] is None
    assert saida["chave_mensagem"] == "textos:boas_vindas"
    turnos = client_pg.get(f"/admin/conversas/{alvo}/turnos").json()["turnos"]
    assert saida["turno_id"] == turnos[0]["id"]
