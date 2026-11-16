"""iCred no ramo INSS (decisão 0027), fase 1.

Postgres real (pulado sem `SATURDAY_TEST_DATABASE_URL`), simulador do motor em
processo e Jev/LLM falsos. Os turnos passam pelo `AgentService`; o resultado da
consulta, pelo job que o worker roda.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest
from conftest import Fakes, _montar_app, settings_icred
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from test_portabilidade_fluxo import anexo_pdf, dados_extrato, idade_anos

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.icred import regras, textos
from saturday.agent.service import AgentService
from saturday.bancos.icred.cliente import ClienteIcred, ErroIcred
from saturday.bancos.icred.normalizacao import normalizar_consulta
from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import (
    Alerta,
    ChamadaExterna,
    Consentimento,
    ConsultaIcred,
    Conversa,
    EventoRecebido,
    Mensagem,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.jobs import icred as job
from saturday.schemas import AgentReply, ChatRequest

# O cliente passa `timeout` ao `httpx`; o `TestClient` do simulador avisa.
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

CPF = "00189004967"
TELEFONE = "5511987654321"


def _produto(simulador: ModuleType, **mudancas: Any) -> dict[str, Any]:
    return {**simulador.PRODUTO_NOVO, **mudancas}


# ------------------------------------------------------------------ cliente


@pytest.fixture
def cliente(fabrica: sessionmaker[Session], http_icred: TestClient) -> ClienteIcred:
    return ClienteIcred(http_icred, settings_icred(), fabrica, dormir=lambda _s: None)


def _linha(fabrica: sessionmaker[Session], id_local: int) -> ConsultaIcred:
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.get_one(ConsultaIcred, id_local)
        sessao.expunge(linha)
        return linha


def test_abrir_consulta_grava_a_linha_e_so_consulta(
    cliente: ClienteIcred, fabrica: sessionmaker[Session], simulador_icred: ModuleType
) -> None:
    id_local = cliente.abrir_consulta(cpf=CPF, telefone="11987654321", nome=None, conversa_id=None)

    linha = _linha(fabrica, id_local)
    assert linha.estado == "na_fila"
    (remota,) = simulador_icred.CONSULTAS.values()
    assert linha.id_externo == remota["id"]
    # Nunca `acao: gravar`: gravaria o que o cliente não viu.
    assert remota["acao"] == "consultar"
    with abrir_sessao(fabrica) as sessao:
        rotas = sessao.scalars(select(ChamadaExterna.rota)).all()
    assert rotas == ["/consultas"]


def test_consulta_recusada_fica_marcada_e_nao_repete(
    fabrica: sessionmaker[Session], http_icred: TestClient, simulador_icred: ModuleType
) -> None:
    errada = settings_icred(icred_chave_api="chave-errada")
    cliente = ClienteIcred(http_icred, errada, fabrica, dormir=lambda _s: None)

    with pytest.raises(ErroIcred) as erro:
        cliente.abrir_consulta(cpf=CPF, telefone="11987654321", nome=None, conversa_id=None)

    assert erro.value.status == 401
    assert simulador_icred.CHAMADAS == [("POST", "/consultas")]
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(ConsultaIcred.estado)).all() == ["falhou"]


def test_limite_por_minuto_vira_erro(cliente: ClienteIcred, simulador_icred: ModuleType) -> None:
    simulador_icred.FALHAS.append(
        {"rota": "/consultas", "metodo": "POST", "status": 429, "vezes": 1}
    )
    with pytest.raises(ErroIcred) as erro:
        cliente.abrir_consulta(cpf=CPF, telefone="11987654321", nome=None, conversa_id=None)
    assert erro.value.status == 429


def test_ler_repete_uma_vez_e_descarta_a_comissao(
    cliente: ClienteIcred, fabrica: sessionmaker[Session], simulador_icred: ModuleType
) -> None:
    id_externo = _linha(
        fabrica,
        cliente.abrir_consulta(cpf=CPF, telefone="11987654321", nome=None, conversa_id=None),
    ).id_externo
    assert id_externo
    simulador_icred.concluir(id_externo, "COM_OFERTA", [dict(simulador_icred.PRODUTO_PORT_REFIN)])
    simulador_icred.FALHAS.append(
        {"rota": f"/consultas/{id_externo}", "metodo": "GET", "status": 500, "vezes": 1}
    )

    resultado = cliente.ler(id_externo)

    assert resultado.final and resultado.situacao == "COM_OFERTA" and resultado.completo
    assert resultado.valido_ate is not None
    assert resultado.contratos == [
        {
            "tipo": "port_refin",
            "produto": "Port + Refin",
            "banco": "Caixa",
            "taxa": "1.85",
            "prazo": 108,
            "parcela": "401.2",
            "liberado": "2501.92",
        }
    ]


def test_contrato_sem_numero_deixa_o_resultado_incompleto() -> None:
    resultado = normalizar_consulta(
        {
            "id": "c_1",
            "estado": "concluida",
            "situacao": "COM_OFERTA",
            "produtos": [{"tipo": "novo"}],
        }
    )
    assert resultado.contratos == [] and not resultado.completo


# ------------------------------------------------------------------ regras


def _contrato(liberado: str = "5000", taxa: str = "1.80", tipo: str = "novo") -> dict[str, Any]:
    return {"tipo": tipo, "taxa": taxa, "prazo": 96, "parcela": "150", "liberado": liberado}


@pytest.mark.parametrize(
    ("situacao", "contratos", "valor_c6", "esperado"),
    [
        ("COM_OFERTA", [_contrato()], "0", (regras.OFERTA, None)),
        ("COM_OFERTA", [_contrato(taxa="1.85")], "0", (regras.OFERTA, None)),
        (
            "COM_OFERTA",
            [_contrato(), _contrato(taxa="1.86")],
            "0",
            (regras.HANDOFF, "icred_taxa_alta"),
        ),
        # O C6 ganha no empate.
        ("COM_OFERTA", [_contrato("5000")], "5000", (regras.SEGUIR, None)),
        ("COM_OFERTA", [_contrato("3000"), _contrato("2500")], "5000", (regras.OFERTA, None)),
        ("COM_OFERTA", [], "0", (regras.HANDOFF, "icred_conferir")),
        ("COM_OFERTA", None, "0", (regras.HANDOFF, "icred_conferir")),
        ("JA_GRAVADO", [], "0", (regras.HANDOFF, "icred_bloqueio")),
        ("PROPOSTA_EXISTENTE", [], "0", (regras.HANDOFF, "icred_bloqueio")),
        ("TELEFONE_VINCULADO", [], "0", (regras.HANDOFF, "icred_bloqueio")),
        ("SEM_COMISSAO", [], "0", (regras.SEGUIR, None)),
        ("ERRO", [], "0", (regras.SEGUIR, None)),
        (None, [], "0", (regras.SEGUIR, None)),
    ],
)
def test_decidir(
    situacao: str | None,
    contratos: list[dict[str, Any]] | None,
    valor_c6: str,
    esperado: tuple[str, str | None],
) -> None:
    assert regras.decidir(situacao, contratos, Decimal(valor_c6)) == esperado


def test_oferta_diz_o_pacote_inteiro_e_avisa_a_estimativa() -> None:
    texto = textos.oferta(
        [_contrato("3000.5"), {**_contrato("2500", tipo="port_refin"), "banco": "Caixa"}]
    )
    assert "R$ 3.000,50 na sua conta, 96 parcelas de R$ 150,00, taxa de 1,80% ao mês" in texto
    assert "Portabilidade com refinanciamento (Caixa)" in texto
    assert "Total na sua conta: R$ 5.500,50." in texto
    assert "estimativa" in texto


# ------------------------------------------------------------------ webhook


@pytest.fixture
def api(service: AgentService, fabrica: sessionmaker[Session]) -> TestClient:
    return TestClient(_montar_app(settings_icred(), service, fabrica))


def _evento(simulador: ModuleType) -> dict[str, Any]:
    simulador.CONSULTAS["c_1"] = simulador._nova_consulta({"cpf": CPF})
    simulador.CONSULTAS["c_1"]["id"] = "c_1"
    return simulador.concluir("c_1", "SEM_COMISSAO")  # type: ignore[no-any-return]


def _eventos_gravados(fabrica: sessionmaker[Session]) -> int:
    with abrir_sessao(fabrica) as sessao:
        return int(sessao.scalar(select(func.count()).select_from(EventoRecebido)) or 0)


def test_webhook_grava_uma_vez_o_evento_assinado(
    api: TestClient, fabrica: sessionmaker[Session], simulador_icred: ModuleType
) -> None:
    corpo, cabecalhos = simulador_icred.requisicao_webhook(_evento(simulador_icred))

    assert api.post("/webhooks/icred", content=corpo, headers=cabecalhos).status_code == 200
    assert api.post("/webhooks/icred", content=corpo, headers=cabecalhos).status_code == 200
    assert _eventos_gravados(fabrica) == 1


def test_webhook_recusa_assinatura_errada_e_timestamp_velho(
    api: TestClient, fabrica: sessionmaker[Session], simulador_icred: ModuleType
) -> None:
    evento = _evento(simulador_icred)
    corpo, cabecalhos = simulador_icred.requisicao_webhook(evento)

    adulterado = api.post("/webhooks/icred", content=corpo + b" ", headers=cabecalhos)
    assert adulterado.status_code == 401

    # Assinatura certa para um timestamp de 6 minutos atrás: replay.
    corpo, velho = simulador_icred.requisicao_webhook(evento, int(time.time()) - 360)
    assert api.post("/webhooks/icred", content=corpo, headers=velho).status_code == 401
    assert _eventos_gravados(fabrica) == 0


def test_webhook_sem_segredo_recusa_tudo(
    service: AgentService, fabrica: sessionmaker[Session], simulador_icred: ModuleType
) -> None:
    sem_segredo = TestClient(
        _montar_app(settings_icred(icred_webhook_segredo=""), service, fabrica)
    )
    corpo, cabecalhos = simulador_icred.requisicao_webhook(_evento(simulador_icred))
    assert sem_segredo.post("/webhooks/icred", content=corpo, headers=cabecalhos).status_code == 503


# ------------------------------------------------------------------ jornada


class Jornada:
    """Uma conversa de WhatsApp do ramo INSS com o iCred ligado."""

    def __init__(
        self,
        fabrica: sessionmaker[Session],
        http: TestClient,
        fakes: Fakes,
        simulador: ModuleType,
    ) -> None:
        settings = settings_icred()
        self.cliente = ClienteIcred(http, settings, fabrica, dormir=lambda _s: None)
        self.fabrica = fabrica
        self.simulador = simulador
        self.id = f"icred-{uuid.uuid4().hex[:10]}"
        checkpointer = InMemorySaver()
        self.servico = AgentService(
            graph=build_graph(checkpointer),
            context=AgentContext(
                jev=fakes.jev,  # type: ignore[arg-type]
                llm=fakes.llm,  # type: ignore[arg-type]
                anexos=fakes.anexos,  # type: ignore[arg-type]
                fabrica=fabrica,
                icred=self.cliente,
            ),
            webhook=fakes.webhook,  # type: ignore[arg-type]
            settings=settings,
            checkpointer=checkpointer,
            fabrica=fabrica,
            storage=None,
        )

    def falar(self, mensagem: str = "", **extras: Any) -> AgentReply:
        return self.servico.process_message(
            ChatRequest(
                conversation_id=self.id,
                message_id=f"wamid.{uuid.uuid4().hex}",
                message=mensagem,
                **extras,
            ),
            OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001"),
        )

    def extrato(self) -> AgentReply:
        return self.falar(
            attachments=[anexo_pdf()], cliente={"data_nascimento": idade_anos(64), "uf": "MS"}
        )

    def ate_a_consulta(self) -> str:
        """Extrato, SIM e CPF; devolve o id da consulta no motor."""

        assert self.extrato().answer == textos.PEDIR_SIM
        assert self.falar("sim").answer == textos.PEDIR_CPF
        assert self.falar(CPF).answer == textos.CONSULTANDO
        (id_externo,) = self.simulador.CONSULTAS
        return str(id_externo)

    def resultado(self, situacao: str, produtos: list[dict[str, Any]] | None = None) -> None:
        (id_externo,) = self.simulador.CONSULTAS
        evento = self.simulador.concluir(id_externo, situacao, produtos)
        job.aplicar(self.fabrica, evento, self.servico)

    def estado(self) -> dict[str, Any]:
        return dict(self.servico.estado_atual(self.servico.config(self.id)))

    def ultima_saida(self) -> str:
        with abrir_sessao(self.fabrica) as sessao:
            return str(
                sessao.scalars(
                    select(Mensagem.conteudo)
                    .join(Conversa, Conversa.id == Mensagem.conversa_id)
                    .where(Conversa.conversation_id == self.id, Mensagem.direcao == "saida")
                    .order_by(Mensagem.id.desc())
                ).first()
            )

    def provas(self) -> list[tuple[str, str | None, str]]:
        with abrir_sessao(self.fabrica) as sessao:
            linhas = sessao.scalars(select(Consentimento).order_by(Consentimento.id)).all()
            return [(p.tipo, p.cpf, p.resposta_literal) for p in linhas]


@pytest.fixture
def jornada(
    fabrica: sessionmaker[Session],
    http_icred: TestClient,
    fakes: Fakes,
    simulador_icred: ModuleType,
) -> Jornada:
    fakes.llm.extrato = dados_extrato()
    return Jornada(fabrica, http_icred, fakes, simulador_icred)


def test_sim_cpf_consulta_oferta_e_aceite(jornada: Jornada, simulador_icred: ModuleType) -> None:
    id_externo = jornada.ate_a_consulta()

    remota = simulador_icred.CONSULTAS[id_externo]
    assert (remota["cpf"], remota["acao"]) == (CPF, "consultar")
    # A prova do SIM existe antes de a consulta sair (regra 3).
    assert jornada.provas() == [("icred_consulta", CPF, "sim")]

    produto = _produto(simulador_icred, liberado=50000.0)
    jornada.resultado("COM_OFERTA", [produto])

    contratos = jornada.estado()["icred"]["contratos"]
    assert jornada.ultima_saida() == textos.oferta(contratos)
    assert "R$ 50.000,00 na sua conta" in jornada.ultima_saida()
    # A comissão não entra no estado.
    assert "comissao" not in str(jornada.estado()["icred"])

    aceite = jornada.falar("sim, quero")
    assert (aceite.status, aceite.handoff_reason) == ("handoff", "icred_aceite")
    assert jornada.provas()[-1] == ("icred_aceite", CPF, "sim, quero")
    # Fase 1: o agente não grava a proposta.
    assert [c for c in simulador_icred.CHAMADAS if c[0] == "POST"] == [("POST", "/consultas")]


def test_nao_no_pedido_de_consulta_segue_para_a_oferta_do_c6(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    assert jornada.extrato().answer == textos.PEDIR_SIM

    resposta = jornada.falar("não")

    assert resposta.status == "answered"
    assert (resposta.answer or "").startswith("Analisei o seu extrato.")
    assert simulador_icred.CHAMADAS == []
    assert jornada.provas() == []


def test_cpf_invalido_duas_vezes_segue_sem_o_icred(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("sim")

    assert jornada.falar("123").answer == textos.CPF_INVALIDO
    assert (jornada.falar("11111111111").answer or "").startswith("Analisei o seu extrato.")
    assert simulador_icred.CHAMADAS == []


@pytest.mark.parametrize("situacao", ["SEM_COMISSAO", "INELEGIVEL", "ERRO"])
def test_sem_oferta_segue_o_caminho_de_antes(jornada: Jornada, situacao: str) -> None:
    jornada.ate_a_consulta()

    jornada.resultado(situacao)

    assert jornada.ultima_saida().startswith("Analisei o seu extrato.")
    assert jornada.estado()["icred"]["etapa"] == "fim"


def test_c6_melhor_que_o_icred_apresenta_o_c6(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.ate_a_consulta()

    jornada.resultado("COM_OFERTA", [_produto(simulador_icred, liberado=1.0)])

    assert jornada.ultima_saida().startswith("Analisei o seu extrato.")


@pytest.mark.parametrize(
    ("situacao", "taxa", "motivo"),
    [
        ("COM_OFERTA", 1.9, "icred_taxa_alta"),
        ("JA_GRAVADO", 1.8, "icred_bloqueio"),
        ("PROPOSTA_EXISTENTE", 1.8, "icred_bloqueio"),
    ],
)
def test_bloqueio_e_taxa_alta_vao_para_o_atendente(
    jornada: Jornada, simulador_icred: ModuleType, situacao: str, taxa: float, motivo: str
) -> None:
    jornada.ate_a_consulta()

    produtos = [_produto(simulador_icred, taxa=taxa, liberado=50000.0)]
    jornada.resultado(situacao, produtos if situacao == "COM_OFERTA" else None)

    with abrir_sessao(jornada.fabrica) as sessao:
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == jornada.id)
        ).one()
        assert conversa.atendimento == "handoff"
        alerta = sessao.scalars(select(Alerta).where(Alerta.conversa_id == conversa.id)).one()
        assert (alerta.detalhe or {}).get("motivo") == motivo
    assert "R$" not in jornada.ultima_saida()


def test_resultado_repetido_nao_fala_duas_vezes(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.ate_a_consulta()
    produto = _produto(simulador_icred, liberado=50000.0)
    jornada.resultado("COM_OFERTA", [produto])
    (evento,) = simulador_icred.EVENTOS

    job.aplicar(jornada.fabrica, evento, jornada.servico)

    with abrir_sessao(jornada.fabrica) as sessao:
        ofertas = sessao.scalar(
            select(func.count())
            .select_from(Mensagem)
            .where(Mensagem.direcao == "saida", Mensagem.conteudo.like("Consultei o iCred%"))
        )
    assert ofertas == 1


def test_consulta_sem_resposta_no_prazo_segue_e_abre_alerta(jornada: Jornada) -> None:
    jornada.ate_a_consulta()
    with abrir_sessao(jornada.fabrica) as sessao:
        sessao.execute(update(ConsultaIcred).values(criada_em=func.now() - timedelta(minutes=6)))

    assert job.verificar_prazo(jornada.fabrica, jornada.cliente, jornada.servico) == 1

    assert jornada.ultima_saida().startswith("Analisei o seu extrato.")
    with abrir_sessao(jornada.fabrica) as sessao:
        assert sessao.scalars(select(ConsultaIcred.estado)).all() == ["desistida"]
        alerta = sessao.scalars(select(Alerta)).one()
        assert alerta.tipo == "icred_consulta_parada"
    # O resultado que chega depois não reabre a oferta.
    jornada.resultado("COM_OFERTA", [dict(jornada.simulador.PRODUTO_NOVO)])
    assert jornada.ultima_saida().startswith("Analisei o seu extrato.")


def test_prazo_vencido_com_a_consulta_pronta_usa_o_resultado(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    id_externo = jornada.ate_a_consulta()
    # O webhook se perdeu: a consulta terminou no motor e ninguém avisou.
    simulador_icred.concluir(
        id_externo, "COM_OFERTA", [_produto(simulador_icred, liberado=50000.0)]
    )
    with abrir_sessao(jornada.fabrica) as sessao:
        sessao.execute(update(ConsultaIcred).values(criada_em=func.now() - timedelta(minutes=6)))

    assert job.verificar_prazo(jornada.fabrica, jornada.cliente, jornada.servico) == 0

    assert jornada.ultima_saida().startswith("Consultei o iCred")


def test_motor_fora_do_ar_segue_sem_o_icred(jornada: Jornada, simulador_icred: ModuleType) -> None:
    simulador_icred.FALHAS.append(
        {"rota": "/consultas", "metodo": "POST", "status": 500, "vezes": 1}
    )
    jornada.extrato()
    jornada.falar("sim")

    resposta = jornada.falar(CPF)

    assert (resposta.answer or "").startswith("Analisei o seu extrato.")
    assert simulador_icred.CHAMADAS == [("POST", "/consultas")]


def test_sem_o_icred_ligado_o_ramo_inss_nao_muda(service: AgentService, fakes: Fakes) -> None:
    fakes.llm.extrato = dados_extrato()
    resposta = service.process_message(
        ChatRequest(
            conversation_id=f"icred-{uuid.uuid4().hex[:10]}",
            attachments=[anexo_pdf()],  # type: ignore[list-item]
            cliente={"data_nascimento": idade_anos(64), "uf": "MS"},  # type: ignore[arg-type]
        ),
        OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001"),
    )
    assert (resposta.answer or "").startswith("Analisei o seu extrato.")


# ------------------------------------------------- achados da revisão do diff


def _atendimento(jornada: Jornada) -> str:
    with abrir_sessao(jornada.fabrica) as sessao:
        return str(
            sessao.scalars(
                select(Conversa.atendimento).where(Conversa.conversation_id == jornada.id)
            ).one()
        )


def test_so_o_sim_explicito_autoriza_e_a_duvida_nao_prende_a_rota(jornada: Jornada) -> None:
    jornada.extrato()

    # "tenho" é sim na triagem do CLT, mas não é consentimento (regra 3).
    assert jornada.falar("tenho uma dúvida").answer != textos.PEDIR_CPF
    assert jornada.estado()["icred"]["etapa"] == "sim"
    assert jornada.provas() == []
    # A rota da dúvida não fica no checkpoint: o SIM seguinte pede o CPF.
    assert jornada.falar("sim").answer == textos.PEDIR_CPF


def test_segunda_resposta_sem_sim_nem_nao_entrega_o_resultado_do_extrato(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.extrato()
    jornada.falar("ok")

    assert (jornada.falar("e o resultado?").answer or "").startswith("Analisei o seu extrato.")
    assert simulador_icred.CHAMADAS == []


def test_pergunta_na_oferta_nao_e_aceite(jornada: Jornada, simulador_icred: ModuleType) -> None:
    jornada.ate_a_consulta()
    jornada.resultado("COM_OFERTA", [_produto(simulador_icred, liberado=50000.0)])

    jornada.falar("tem seguro?")

    assert _atendimento(jornada) != "handoff"
    assert [tipo for tipo, _cpf, _resposta in jornada.provas()] == ["icred_consulta"]


def test_extrato_repetido_mantem_a_pergunta_do_icred(jornada: Jornada) -> None:
    assert jornada.extrato().answer == textos.PEDIR_SIM

    assert jornada.extrato().answer == textos.PEDIR_SIM
    assert jornada.falar("sim").answer == textos.PEDIR_CPF


def test_pacote_lido_pela_metade_vai_para_o_atendente(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    jornada.ate_a_consulta()

    inteiro = _produto(simulador_icred, liberado=50000.0)
    jornada.resultado("COM_OFERTA", [inteiro, _produto(simulador_icred, parcela=None)])

    assert _atendimento(jornada) == "handoff"
    assert "R$" not in jornada.ultima_saida()


def test_cpf_com_consulta_aberta_em_outra_conversa_segue_sem_o_icred(
    jornada: Jornada, fabrica: sessionmaker[Session], http_icred: TestClient, fakes: Fakes
) -> None:
    jornada.ate_a_consulta()
    outra = Jornada(fabrica, http_icred, fakes, jornada.simulador)
    outra.extrato()
    outra.falar("sim")

    # O motor devolve a consulta da primeira conversa (`ja_existia`).
    assert (outra.falar(CPF).answer or "").startswith("Analisei o seu extrato.")
    assert outra.estado()["icred"]["etapa"] == "fim"


def test_evento_de_consulta_desconhecida_falha_para_a_fila_tentar_de_novo(
    jornada: Jornada,
) -> None:
    dados = {"id": "nao-existe", "estado": "concluida"}
    evento = {"evento": job.CONSULTA_CONCLUIDA, "dados": dados}

    with pytest.raises(ValueError, match="desconhecida"):
        job.aplicar(jornada.fabrica, evento, jornada.servico)


def test_desistir_de_evento_sem_id_nao_toca_em_conversa_alheia(
    jornada: Jornada, simulador_icred: ModuleType
) -> None:
    # Deixa uma linha `falhou`, sem id do motor.
    simulador_icred.FALHAS.append(
        {"rota": "/consultas", "metodo": "POST", "status": 500, "vezes": 1}
    )
    jornada.extrato()
    jornada.falar("sim")
    jornada.falar(CPF)

    job.desistir(jornada.fabrica, {"evento": job.CONSULTA_CONCLUIDA}, jornada.servico)

    assert _atendimento(jornada) != "handoff"


def test_turno_que_falha_no_prazo_manda_a_conversa_para_um_humano(
    jornada: Jornada, monkeypatch: pytest.MonkeyPatch
) -> None:
    jornada.ate_a_consulta()
    with abrir_sessao(jornada.fabrica) as sessao:
        sessao.execute(update(ConsultaIcred).values(criada_em=func.now() - timedelta(minutes=6)))

    def quebra(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("turno quebrou")

    monkeypatch.setattr(jornada.servico, "continuar", quebra)

    assert job.verificar_prazo(jornada.fabrica, jornada.cliente, jornada.servico) == 1
    assert _atendimento(jornada) == "handoff"
