"""Edição da ficha e respostas rápidas pelo painel (compositor da conversa)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from conftest import entrar
from sqlalchemy import select
from test_painel_api import _cliente_escreve, _conversa_id, _criar

from saturday.agent.icred import textos as textos_icred
from saturday.agent.service import ficha_do_estado
from saturday.dados import repositorios
from saturday.dados.modelos import (
    Auditoria,
    Consentimento,
    ConsultaGranatech,
    ConsultaIcred,
    Conversa,
    PropostaGranatech,
)
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
    csrf = entrar(client, "ana@exemplo.test")
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
    csrf = entrar(client_pg, "ana@exemplo.test")
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
    csrf = entrar(client_pg, "ana@exemplo.test")
    rota = f"/admin/conversas/{alvo}/ficha"

    assert client_pg.patch(rota, headers=csrf, json={"sexo": "F"}).status_code == 403
    client_pg.post(f"/admin/conversas/{alvo}/assumir", headers=csrf)
    for invalido in ({"cpf": "11111111111"}, {"nome": "Maria"}, {"outro": "x"}):
        assert client_pg.patch(rota, headers=csrf, json=invalido).status_code == 422
    assert client_pg.patch(rota, headers=csrf, json={}).status_code == 422
    assert client_pg.patch(rota, json={"sexo": "F"}).status_code == 403


def test_ficha_mostra_a_ultima_consulta_do_icred(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    entrar(client_pg, "ana@exemplo.test")
    rota = f"/admin/conversas/{alvo}/ficha"
    assert client_pg.get(rota).json()["icred"] is None

    contrato = {"tipo": "novo", "taxa": "1.80", "prazo": 84, "parcela": "100", "liberado": "5000"}
    with abrir(fabrica) as s:
        s.add(
            ConsultaIcred(
                chave=uuid.uuid4().hex,
                cpf="00189004967",
                conversa_id=uuid.UUID(alvo),
                estado="concluida",
                situacao="COM_OFERTA",
                contratos=[contrato],
            )
        )

    icred = client_pg.get(rota).json()["icred"]
    assert (icred["situacao"], icred["contratos"]) == ("COM_OFERTA", [contrato])
    # O CPF da consulta não sai por aqui: ele já está na ficha, mascarado.
    assert "cpf" not in icred


def test_ficha_nao_mostra_como_vigente_a_consulta_do_titular_descartado(
    client_pg, service_pg, fabrica, ana, conversa
):
    _cliente_escreve(service_pg, conversa, "oi")
    alvo = _conversa_id(fabrica, conversa)
    entrar(client_pg, "ana@exemplo.test")
    rota = f"/admin/conversas/{alvo}/ficha"
    with abrir(fabrica) as s:
        linha = ConsultaIcred(
            chave=uuid.uuid4().hex,
            cpf="00189004967",
            conversa_id=uuid.UUID(alvo),
            estado="desistida",
        )
        s.add(linha)
        s.flush()
        consulta = linha.id
    config = service_pg.config(conversa)

    # Prazo de espera vencido: a consulta desistida ainda é a da conversa.
    service_pg.graph.update_state(config, {"icred": {"etapa": "fim", "consulta": consulta}})
    assert client_pg.get(rota).json()["icred"]["situacao"] is None

    # Extrato de outro titular: o estado do iCred recomeçou sem ela.
    service_pg.graph.update_state(config, {"icred": {"etapa": "sim"}})
    assert client_pg.get(rota).json()["icred"]["situacao"] == "OUTRO_TITULAR"


def test_ficha_mostra_o_contrato_novo_do_c6(client_pg, service_pg, fabrica, ana, conversa):
    _cliente_escreve(service_pg, conversa, "oi")
    rota = f"/admin/conversas/{_conversa_id(fabrica, conversa)}/ficha"
    entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get(rota).json()["contrato_novo"] is None

    condicao = {
        "valor": "4321.09",
        "parcela": "99.00",
        "parcelas": 108,
        "taxa": "1.85",
        "convenio": "000020",
        "produto": "0001",
    }
    config = service_pg.config(conversa)
    for situacao in ("ofertado", "aceito", "recusado"):
        # Chave a mais no estado não sai: a lista de campos é fixa.
        guardado = {"situacao": situacao, **condicao, "outro": "x"}
        service_pg.graph.update_state(config, {"c6_novo": guardado})
        assert client_pg.get(rota).json()["contrato_novo"] == {
            "situacao": situacao,
            "valor": "4321.09",
            "valor_parcela": "99.00",
            "numero_parcelas": 108,
            "taxa_mensal": "1.85",
            "convenio": "000020",
            "produto": "0001",
        }

    # Simulou e não achou condição: não há o que mostrar.
    service_pg.graph.update_state(config, {"c6_novo": {"situacao": "sem_oferta"}})
    assert client_pg.get(rota).json()["contrato_novo"] is None


CONTRATO_NOVO = {
    "situacao": "ofertado",
    "valor": "4321.09",
    "parcela": "99.00",
    "parcelas": 108,
    "taxa": "1.85",
}
PACOTE_ICRED = [
    {"tipo": "novo", "taxa": "1.80", "prazo": 84, "parcela": "100", "liberado": "5000"},
    {
        "tipo": "port",
        "banco": "BMG",
        "taxa": "1.70",
        "prazo": 96,
        "parcela": "210.5",
        "liberado": 0,
    },
]
PORTABILIDADE = {
    "ok": True,
    "troco_faixa": {"min": 2469.12, "max": 3001.98},
    "contratos": [
        {"banco": "BMG", "elegivel": True, "troco_faixa": {"min": 1234.56, "max": 1500.99}},
        {"banco": "PAN", "elegivel": True, "troco_faixa": {"min": 1234.56, "max": 1500.99}},
        {"banco": "C6", "elegivel": False, "motivo": "ja_c6", "troco_faixa": {"min": 0, "max": 0}},
    ],
}


def _ficha_de(client, service, fabrica, conversation_id):
    """Para uma conversa nova: quem lê a ficha, quem grava estado e quem grava fala fixa."""

    _cliente_escreve(service, conversation_id, "oi")
    alvo = _conversa_id(fabrica, conversation_id)
    entrar(client, "ana@exemplo.test")

    def estado(valores):
        service.graph.update_state(service.config(conversation_id), valores)

    def fala(chave):
        with abrir(fabrica) as s:
            repositorios.registrar_saida(
                s, s.get(Conversa, uuid.UUID(alvo)), conteudo="fala fixa", chave_mensagem=chave
            )

    return (lambda: client.get(f"/admin/conversas/{alvo}/ficha").json()), estado, fala


def test_oferta_vigente_e_o_contrato_novo_do_c6(client_pg, service_pg, fabrica, ana, conversa):
    ficha, estado, _ = _ficha_de(client_pg, service_pg, fabrica, conversa)
    assert ficha()["oferta_vigente"] is None

    estado({"c6_novo": CONTRATO_NOVO})

    # Os reais que a fala de oferta mostra: valor na conta e parcela.
    assert ficha()["oferta_vigente"] == {
        "ramo": "contrato_novo",
        "situacao": "vigente",
        "valores": ["4321.09", "99.00"],
    }

    estado({"c6_novo": {"situacao": "sem_oferta"}})
    assert ficha()["oferta_vigente"] is None


def test_oferta_vigente_e_a_do_credito_do_trabalhador(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, _ = _ficha_de(client_pg, service_pg, fabrica, conversa)
    oferta = {"liberado": "4619.53", "valor_parcela": "300.00", "valor_seguro": "503.32"}

    estado({"clt": {"oferta": oferta}})

    assert ficha()["oferta_vigente"] == {
        "ramo": "clt",
        "situacao": "vigente",
        "valores": ["4619.53", "300.00", "503.32"],
    }


def test_oferta_vigente_e_o_pacote_do_icred(client_pg, service_pg, fabrica, ana, conversa):
    ficha, estado, _ = _ficha_de(client_pg, service_pg, fabrica, conversa)

    estado({"icred": {"etapa": "oferta", "contratos": PACOTE_ICRED}})

    # Liberado e parcela de cada contrato e, com mais de um, o total na conta.
    assert ficha()["oferta_vigente"] == {
        "ramo": "icred",
        "situacao": "vigente",
        "valores": ["5000.00", "100.00", "0.00", "210.50", "5000.00"],
    }

    estado({"icred": {"etapa": "oferta", "contratos": PACOTE_ICRED[:1]}})
    assert ficha()["oferta_vigente"]["valores"] == ["5000.00", "100.00"]


def test_oferta_vigente_e_a_portabilidade_depois_de_apresentada(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, fala = _ficha_de(client_pg, service_pg, fabrica, conversa)

    # Calculada e ainda não mostrada ao cliente (o iCred pergunta antes): não vale.
    estado({"portability_result": PORTABILIDADE})
    atual = ficha()
    assert (atual["oferta_vigente"], atual["portabilidade_oferta"]) == (None, None)

    fala("inss:oferta")

    # A fala mostra reais inteiros, truncados: a faixa do total e a de cada contrato.
    atual = ficha()
    assert atual["oferta_vigente"] == {
        "ramo": "portabilidade",
        "situacao": "vigente",
        "valores": ["2469", "3001", "1234", "1500", "1234", "1500"],
    }
    assert atual["portabilidade_oferta"] == {
        "minimo": 2469,
        "maximo": 3001,
        "contratos": [
            {"banco": "BMG", "minimo": 1234, "maximo": 1500},
            {"banco": "PAN", "minimo": 1234, "maximo": 1500},
        ],
    }


def test_com_duas_ofertas_a_vigente_e_a_ultima_mostrada(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, fala = _ficha_de(client_pg, service_pg, fabrica, conversa)
    estado(
        {
            "c6_novo": {**CONTRATO_NOVO, "situacao": "recusado"},
            "icred": {"etapa": "oferta", "contratos": PACOTE_ICRED[:1]},
        }
    )

    # Falas sem chave (anteriores à decisão 0018) não dizem qual saiu por último.
    assert ficha()["oferta_vigente"] is None

    fala("textos:oferta_contrato_novo")
    fala("icred:oferta")
    assert ficha()["oferta_vigente"]["ramo"] == "icred"

    # A chave junta as partes da fala com `+`.
    fala("textos:oferta_contrato_novo+textos:fora_horario")
    assert ficha()["oferta_vigente"]["ramo"] == "contrato_novo"

    # A última oferta mostrada saiu do estado (extrato novo): não há vigente.
    fala("inss:oferta")
    assert ficha()["oferta_vigente"] is None

    # No CLT a oferta pode sair junto com o aviso do teto.
    estado({"clt": {"oferta": {"liberado": "6999.00", "valor_parcela": "300.00"}}})
    fala("aviso_teto+oferta")
    assert ficha()["oferta_vigente"] == {
        "ramo": "clt",
        "situacao": "vigente",
        "valores": ["6999.00", "300.00"],
    }


def test_contrato_novo_recusado_segue_conferindo_e_sai_como_recusado(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, _ = _ficha_de(client_pg, service_pg, fabrica, conversa)

    estado({"c6_novo": {**CONTRATO_NOVO, "situacao": "recusado"}})

    assert ficha()["oferta_vigente"] == {
        "ramo": "contrato_novo",
        "situacao": "recusada",
        "valores": ["4321.09", "99.00"],
    }

    estado({"c6_novo": {**CONTRATO_NOVO, "situacao": "aceito"}})
    assert ficha()["oferta_vigente"]["situacao"] == "vigente"


def test_pacote_do_icred_recusado_sai_como_recusado_e_o_aceito_nao(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, _ = _ficha_de(client_pg, service_pg, fabrica, conversa)
    pacote = PACOTE_ICRED[:1]

    # Jornada do iCred encerrada com o pacote e sem prova de aceite: o cliente disse NÃO.
    estado({"icred": {"etapa": "fim", "contratos": pacote}})
    vigente = ficha()["oferta_vigente"]
    assert (vigente["situacao"], vigente["valores"]) == ("recusada", ["5000.00", "100.00"])

    # O SIM grava a prova: encerrada, mas aceita. Basta a prova existir; o
    # texto da oferta pode mudar de versão sem virar recusa.
    with abrir(fabrica) as s:
        s.add(
            Consentimento(
                conversa_id=s.scalar(select(Conversa.id)),
                tipo="icred_aceite",
                texto_mostrado="oferta em um texto de versão antiga",
                versao=textos_icred.VERSAO,
                resposta_literal="sim",
                cpf="00189004967",
            )
        )
    assert ficha()["oferta_vigente"]["situacao"] == "vigente"


def test_portabilidade_recusada_sai_como_recusada_ate_ser_mostrada_de_novo(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, fala = _ficha_de(client_pg, service_pg, fabrica, conversa)
    estado({"portability_result": PORTABILIDADE})
    fala("inss:oferta")
    assert ficha()["oferta_vigente"]["situacao"] == "vigente"

    # A fala fixa da recusa é o que a conversa guarda do NÃO à portabilidade.
    fala("textos:recusa")
    atual = ficha()
    assert (atual["oferta_vigente"]["ramo"], atual["oferta_vigente"]["situacao"]) == (
        "portabilidade",
        "recusada",
    )
    assert atual["portabilidade_oferta"]["minimo"] == 2469

    fala("inss:oferta")
    assert ficha()["oferta_vigente"]["situacao"] == "vigente"


def test_fala_fixa_de_oferta_e_conferida_contra_a_oferta_do_proprio_ramo(
    client_pg, service_pg, fabrica, ana, conversa
):
    ficha, estado, fala = _ficha_de(client_pg, service_pg, fabrica, conversa)
    estado(
        {
            "c6_novo": {**CONTRATO_NOVO, "situacao": "recusado"},
            "portability_result": PORTABILIDADE,
        }
    )
    fala("textos:oferta_contrato_novo")
    fala("inss:oferta+textos:fora_horario")
    fala("textos:recusa")

    # A ficha leva a oferta de cada ramo que o estado guarda, além da vigente.
    atual = ficha()
    assert atual["oferta_vigente"]["ramo"] == "portabilidade"
    assert atual["ofertas"] == {
        "contrato_novo": {"situacao": "recusada", "valores": ["4321.09", "99.00"]},
        "portabilidade": {
            "situacao": "recusada",
            "valores": ["2469", "3001", "1234", "1500", "1234", "1500"],
        },
    }

    # E cada fala diz de que ramo é a oferta que ela apresenta, se apresenta alguma.
    alvo = _conversa_id(fabrica, conversa)
    mensagens = client_pg.get(f"/admin/conversas/{alvo}").json()["mensagens"]
    assert [m["ramo_da_oferta"] for m in mensagens if m["conteudo"] == "fala fixa"] == [
        "contrato_novo",
        "portabilidade",
        None,
    ]


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
    gestor = entrar(client_pg, "gil@exemplo.test")

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

    atendente = entrar(client_pg, "ana@exemplo.test")
    assert client_pg.get(rota).json() == [{"id": rid, "atalho": "pix", "texto": "Mande o Pix."}]
    nova = {"atalho": "a", "texto": "b"}
    assert client_pg.post(rota, headers=atendente, json=nova).status_code == 403
    assert client_pg.delete(f"{rota}/{rid}", headers=atendente).status_code == 403

    gestor = entrar(client_pg, "gil@exemplo.test")
    assert client_pg.delete(f"{rota}/{rid}", headers=gestor).status_code == 204
    assert {
        "resposta_rapida:criar",
        "resposta_rapida:editar",
        "resposta_rapida:apagar",
    } <= set(_acoes(fabrica))


# ------------------------------------------------------------------ ler a ficha


@pytest.mark.parametrize(
    ("semente", "campos"),
    [
        (
            {"clt": {"etapa": "dados_proposta", "dados": {"nome": "Maria"}}},
            {
                "nome": "Maria Silva",
                "cpf": "00189004967",
                "nascimento": "1990-05-20",
                "email": "maria@exemplo.test",
            },
        ),
        (
            {"cliente": {"nome": "João"}},
            {"nome": "João Pereira", "cpf": "00189004967", "nascimento": "1960-01-31"},
        ),
    ],
    ids=["clt", "inss"],
)
def test_o_que_a_edicao_grava_a_leitura_devolve(service, semente, campos):
    config = service.config("ficha-ida-e-volta")
    service.graph.update_state(config, semente)

    service.editar_ficha("ficha-ida-e-volta", campos)

    assert ficha_do_estado(service.estado_atual(config)) == campos
