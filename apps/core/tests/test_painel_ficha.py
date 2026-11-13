"""Edição da ficha e respostas rápidas pelo painel (compositor da conversa)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from test_painel_api import _cliente_escreve, _conversa_id, _criar, _entrar

from saturday.dados.modelos import Auditoria, ConsultaGranatech, PropostaGranatech
from saturday.dados.sessao import sessao as abrir


@pytest.fixture
def ana(fabrica):
    return _criar(fabrica, "ana@exemplo.test")


CONTA = {
    "banco_codigo": "341",
    "banco_nome": "Itaú",
    "agencia": "1234",
    "numero_conta": "56789",
    "digito_conta": "0",
    "tipo_conta": "conta_corrente",
}


def _ficha_clt(client, service, fabrica, conversation_id):
    _cliente_escreve(service, conversation_id, "oi")
    clt = {"etapa": "dados_proposta", "dados": {"nome": "Maria Silva"}}
    service.graph.update_state(service.config(conversation_id), {"clt": clt})
    alvo = _conversa_id(fabrica, conversation_id)
    csrf = _entrar(client, "ana@exemplo.test")
    assert client.post(f"/admin/conversas/{alvo}/assumir", headers=csrf).status_code == 204
    return alvo, csrf


def _acoes(fabrica):
    with abrir(fabrica) as s:
        return list(s.scalars(select(Auditoria.acao)).all())


# ------------------------------------------------------------------ editar ficha


def test_editar_ficha_grava_no_ramo_clt_e_audita_sem_valores(
    client_pg, service_pg, fabrica, ana, conversa
):
    alvo, csrf = _ficha_clt(client_pg, service_pg, fabrica, conversa)
    mudanca = {
        "nome": "Maria Souza Silva",
        "nascimento": "1988-02-10",
        "sexo": "F",
        "email": "Maria@Exemplo.test",
        "celular": "11912345678",
        "cpf": "001.890.049-67",
        "conta": CONTA,
    }

    resposta = client_pg.patch(f"/admin/conversas/{alvo}/ficha", headers=csrf, json=mudanca)

    assert resposta.status_code == 204, resposta.text
    clt = service_pg.estado_atual(service_pg.config(conversa))["clt"]
    assert clt["etapa"] == "dados_proposta"
    assert clt["dados"] == {
        **mudanca,
        "email": "maria@exemplo.test",
        "cpf": "00189004967",
        "conta": {**CONTA, "digito_agencia": ""},
    }
    with abrir(fabrica) as s:
        registro = s.scalars(
            select(Auditoria).where(Auditoria.acao == "conversa:editar_ficha")
        ).one()
    assert registro.detalhe == {
        "campos": ["celular", "conta", "cpf", "email", "nascimento", "nome", "sexo"]
    }
    assert "00189004967" not in repr(registro.detalhe)


def test_editar_ficha_do_ramo_inss_so_aceita_os_campos_dele(
    client_pg, service_pg, fabrica, ana, conversa
):
    _cliente_escreve(service_pg, conversa, "oi")
    service_pg.graph.update_state(service_pg.config(conversa), {"cliente": {"nome": "João"}})
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    rota = f"/admin/conversas/{alvo}/ficha"

    ok = client_pg.patch(
        rota, headers=csrf, json={"nome": "João Pereira", "nascimento": "1960-01-31"}
    )
    recusada = client_pg.patch(rota, headers=csrf, json={"email": "joao@exemplo.test"})

    assert ok.status_code == 204
    cliente = service_pg.estado_atual(service_pg.config(conversa))["cliente"]
    assert cliente == {"nome": "João Pereira", "data_nascimento": "1960-01-31"}
    assert recusada.status_code == 409
    # A recusa leva a auditoria junto: só a edição que valeu fica.
    assert _acoes(fabrica).count("conversa:editar_ficha") == 1


def test_editar_ficha_exige_ser_dono_e_dado_valido(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    service_pg.graph.update_state(service_pg.config(conversa), {"clt": {"dados": {}}})
    alvo = _conversa_id(fabrica, conversa)
    csrf = _entrar(client_pg, "ana@exemplo.test")
    rota = f"/admin/conversas/{alvo}/ficha"

    assert client_pg.patch(rota, headers=csrf, json={"sexo": "F"}).status_code == 403
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    for invalido in ({"cpf": "11111111111"}, {"nome": "Maria"}, {"outro": "x"}):
        assert client_pg.patch(rota, headers=csrf, json=invalido).status_code == 422
    assert client_pg.patch(rota, headers=csrf, json={}).status_code == 422
    assert client_pg.patch(rota, json={"sexo": "F"}).status_code == 403


def test_cpf_e_conta_travam_depois_do_banco(client_pg, service_pg, fabrica, ana, conversa):
    alvo, csrf = _ficha_clt(client_pg, service_pg, fabrica, conversa)
    rota = f"/admin/conversas/{alvo}/ficha"
    with abrir(fabrica) as s:
        s.add(
            ConsultaGranatech(
                id_externo="c-1", cpf="00189004967", conversa_id=uuid.UUID(alvo), status="SUCCESS"
            )
        )

    assert client_pg.patch(rota, headers=csrf, json={"cpf": "00189004967"}).status_code == 409
    assert client_pg.patch(rota, headers=csrf, json={"conta": CONTA}).status_code == 204

    with abrir(fabrica) as s:
        s.add(
            PropostaGranatech(
                consulta_id=s.scalar(select(ConsultaGranatech.id)),
                conversa_id=uuid.UUID(alvo),
                estado_envio="criada",
                valor_parcela=Decimal("300.00"),
                numero_parcelas=36,
            )
        )
    recusada = client_pg.patch(rota, headers=csrf, json={"conta": CONTA})
    assert recusada.status_code == 409
    assert "Granatech" in recusada.json()["detail"]


# ------------------------------------------------------------------ respostas rápidas


def test_respostas_rapidas_so_o_gestor_mexe(client_pg, fabrica, ana):
    _criar(fabrica, "gil@exemplo.test", "gestor")
    rota = "/admin/respostas-rapidas"
    gestor = _entrar(client_pg, "gil@exemplo.test")

    criada = client_pg.post(rota, headers=gestor, json={"atalho": "pix", "texto": "Envie o Pix."})
    assert criada.status_code == 201
    rid = criada.json()["id"]
    repetida = client_pg.post(rota, headers=gestor, json={"atalho": "pix", "texto": "x"})
    assert repetida.status_code == 409
    invalida = client_pg.post(rota, headers=gestor, json={"atalho": "Com Espaço", "texto": "x"})
    assert invalida.status_code == 422
    editada = client_pg.patch(
        f"{rota}/{rid}", headers=gestor, json={"atalho": "pix", "texto": "Mande o Pix."}
    )
    assert editada.json()["texto"] == "Mande o Pix."

    atendente = _entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get(rota).json() == [{"id": rid, "atalho": "pix", "texto": "Mande o Pix."}]
    nova = {"atalho": "a", "texto": "b"}
    assert client_pg.post(rota, headers=atendente, json=nova).status_code == 403
    assert client_pg.delete(f"{rota}/{rid}", headers=atendente).status_code == 403

    gestor = _entrar(client_pg, "gil@exemplo.test")
    assert client_pg.delete(f"{rota}/{rid}", headers=gestor).status_code == 204
    assert {
        "resposta_rapida:criar",
        "resposta_rapida:editar",
        "resposta_rapida:apagar",
    } <= set(_acoes(fabrica))
