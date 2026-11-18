"""Funil da aba Operação (decisão 0031): etapa × produto, por coorte de conversa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from conftest import entrar_como
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import (
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Mensagem,
    PropostaGranatech,
    Turno,
    UsuarioPainel,
)
from saturday.dados.sessao import sessao as abrir

CPF = "00189004967"
ETAPAS = ["iniciadas", "sim", "oferta", "aceite", "proposta", "pago"]


def _conversa(
    sessao: Session,
    nome: str,
    *,
    etapa: str | None = None,
    motivo: str | None = None,
    dias_atras: int = 0,
    telefone: str | None = None,
) -> Conversa:
    """Conversa com um turno; a etapa do turno diz o público (`inss` ou uma do CLT)."""

    conversa = Conversa(conversation_id=f"funil:{nome}", canal="whatsapp", telefone=telefone)
    if dias_atras:
        conversa.criada_em = datetime.now(UTC) - timedelta(days=dias_atras)
    sessao.add(conversa)
    sessao.flush()
    sessao.add(Turno(conversa_id=conversa.id, caminho=[], etapa=etapa, motivo=motivo))
    return conversa


def _prova(sessao: Session, conversa: Conversa, tipo: str) -> None:
    sessao.add(
        Consentimento(
            conversa_id=conversa.id,
            tipo=tipo,
            texto_mostrado="pedido",
            versao="v",
            resposta_literal="sim",
            cpf=CPF,
        )
    )


def _fala(sessao: Session, conversa: Conversa, chave: str) -> None:
    sessao.add(
        Mensagem(conversa_id=conversa.id, direcao="saida", conteudo="x", chave_mensagem=chave)
    )


def _proposta(
    sessao: Session, conversa: Conversa, *, status: str | None = None, teste: bool = False
) -> None:
    consulta = ConsultaGranatech(
        id_externo=f"c-{conversa.conversation_id}",
        teste=teste,
        cpf=CPF,
        conversa_id=conversa.id,
        status="SUCCESS",
    )
    sessao.add(consulta)
    sessao.flush()
    sessao.add(
        PropostaGranatech(
            consulta_id=consulta.id,
            conversa_id=conversa.id,
            id_externo=f"p-{conversa.conversation_id}",
            teste=teste,
            estado_envio="criada",
            valor_parcela=Decimal("100.00"),
            numero_parcelas=12,
            status=status,
        )
    )


def _funil(client: TestClient, periodo: str = "mes") -> dict[str, Any]:
    resposta = client.get("/admin/funil", params={"periodo": periodo})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()  # type: ignore[no-any-return]


def _coluna(funil: dict[str, Any], produto: str) -> list[Any]:
    """As etapas do produto: ``(conversas, taxa)``, ou ``None`` onde não se aplica."""

    assert [e["id"] for e in funil["etapas"]] == ETAPAS
    [linha] = [p for p in funil["produtos"] if p["id"] == produto]
    return [c and (c["conversas"], c["taxa"]) for c in linha["celulas"]]


def test_clt_conta_cada_etapa_uma_vez_por_conversa(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    with abrir(fabrica) as sessao:
        paga = _conversa(sessao, "paga", etapa="pago")
        for tipo in ("consulta", "consulta", "proposta"):
            _prova(sessao, paga, tipo)
        # A oferta mostrada duas vezes (com e sem seguro) é uma conversa só.
        _fala(sessao, paga, "oferta")
        _fala(sessao, paga, "aviso+oferta_sem_seguro")
        _proposta(sessao, paga, status="PAYED")

        ofertada = _conversa(sessao, "ofertada", etapa="oferta")
        _prova(sessao, ofertada, "consulta")
        _fala(sessao, ofertada, "oferta")

        _conversa(sessao, "triagem", etapa="triagem")
        _conversa(sessao, "so-oi")

    entrar_como(client_pg, fabrica, "gestor")
    funil = _funil(client_pg)

    assert _coluna(funil, "clt") == [(3, None), (2, 67), (2, 100), (1, 50), (1, 100), (1, 100)]
    assert (funil["iniciadas"], funil["sem_publico"]) == (4, 1)


def test_aceite_do_clt_e_o_da_oferta_com_ou_sem_proposta_automatica(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    with abrir(fabrica) as sessao:
        # Proposta automática desligada: o aceite vira handoff, sem prova.
        especialista = _conversa(sessao, "especialista", etapa="oferta", motivo="aceite_clt")
        # Ligada: aceitou e parou na coleta dos dados, antes do SIM ao resumo.
        coleta = _conversa(sessao, "coleta", etapa="dados_proposta")
        divergente = _conversa(sessao, "divergente", etapa="oferta", motivo="dados_divergentes")
        so_oferta = _conversa(sessao, "so-oferta", etapa="oferta")
        for conversa in (especialista, coleta, divergente, so_oferta):
            _prova(sessao, conversa, "consulta")
            _fala(sessao, conversa, "oferta")

    entrar_como(client_pg, fabrica, "gestor")

    assert _coluna(_funil(client_pg), "clt")[2:4] == [(4, 100), (3, 75)]


def test_taxa_arredonda_a_metade_para_cima(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    with abrir(fabrica) as sessao:
        for n in range(8):
            conversa = _conversa(sessao, f"c{n}", etapa="triagem")
            if n == 0:
                _prova(sessao, conversa, "consulta")

    entrar_como(client_pg, fabrica, "gestor")

    # 1 de 8 é 12,5%.
    assert _coluna(_funil(client_pg), "clt")[1] == (1, 13)


def test_inss_etapa_sem_fonte_e_nao_se_aplica(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    with abrir(fabrica) as sessao:
        novo = _conversa(sessao, "novo", etapa="inss", motivo="aceitou_contrato_novo")
        _prova(sessao, novo, "simulacao_c6")
        _fala(sessao, novo, "textos:oferta_contrato_novo")

        port = _conversa(sessao, "port", etapa="inss", motivo="aceitou_portabilidade")
        _fala(sessao, port, "inss:oferta")

        icred = _conversa(sessao, "icred", etapa="inss")
        _prova(sessao, icred, "icred_consulta")
        _fala(sessao, icred, "icred:oferta")
        _prova(sessao, icred, "icred_aceite")

        _conversa(sessao, "so-extrato", etapa="inss")

    entrar_como(client_pg, fabrica, "gestor")
    funil = _funil(client_pg)

    # As três ofertas do INSS partem das mesmas quatro conversas do público.
    assert _coluna(funil, "contrato_novo") == [(4, None), (1, 25), (1, 100), (1, 100), None, None]
    # Sem SIM na portabilidade: a oferta é medida contra as iniciadas.
    assert _coluna(funil, "portabilidade") == [(4, None), None, (1, 25), (1, 100), None, None]
    assert _coluna(funil, "icred") == [(4, None), (1, 25), (1, 100), (1, 100), None, None]
    assert _coluna(funil, "clt")[0] == (0, None)
    assert _coluna(funil, "clt")[1] == (0, None)
    assert (funil["iniciadas"], funil["sem_publico"]) == (4, 0)


def test_periodo_e_a_coorte_da_conversa_iniciada(
    client_pg: TestClient, fabrica: sessionmaker[Session]
) -> None:
    with abrir(fabrica) as sessao:
        antiga = _conversa(sessao, "antiga", etapa="oferta", dias_atras=10)
        # O SIM de hoje numa conversa de dez dias atrás pertence à coorte dela.
        _prova(sessao, antiga, "consulta")
        _conversa(sessao, "de-hoje", etapa="triagem")

    entrar_como(client_pg, fabrica, "gestor")

    assert _coluna(_funil(client_pg, "hoje"), "clt")[:2] == [(1, None), (0, 0)]
    assert _coluna(_funil(client_pg, "7d"), "clt")[:2] == [(1, None), (0, 0)]
    trinta = _funil(client_pg, "30d")
    assert _coluna(trinta, "clt")[:2] == [(2, None), (1, 50)]
    assert trinta["periodo"] == "30d"
    assert trinta["de"] < trinta["ate"]
    assert client_pg.get("/admin/funil", params={"periodo": "ano"}).status_code == 422


def test_conversa_de_teste_fica_fora(client_pg: TestClient, fabrica: sessionmaker[Session]) -> None:
    with abrir(fabrica) as sessao:
        sessao.add(
            UsuarioPainel(
                email="dev-funil@exemplo.test",
                senha_hash="x",
                perfil="atendente",
                nome="Dev",
                telefone="11987654321",
                pode_testar_fluxos=True,
            )
        )
        membro = _conversa(sessao, "membro", etapa="oferta", telefone="11987654321")
        _prova(sessao, membro, "consulta")
        # Proposta do simulador em conversa de cliente (o membro perdeu a permissão).
        cliente = _conversa(sessao, "cliente", etapa="proposta", telefone="21912345678")
        _proposta(sessao, cliente, status="PAYED", teste=True)

    entrar_como(client_pg, fabrica, "gestor")
    funil = _funil(client_pg)

    assert _coluna(funil, "clt") == [(1, None), (0, 0), (0, None), (0, None), (0, None), (0, None)]
    assert funil["iniciadas"] == 1


def test_funil_e_so_do_gestor(client_pg: TestClient, fabrica: sessionmaker[Session]) -> None:
    entrar_como(client_pg, fabrica, "atendente")
    assert client_pg.get("/admin/funil").status_code == 403
