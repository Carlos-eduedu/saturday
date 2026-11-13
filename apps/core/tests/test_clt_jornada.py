"""Jornadas do ramo CLT até a oferta (Fase 5), ponta a ponta.

Postgres real (pulado sem `SATURDAY_TEST_DATABASE_URL`), simulador da Granatech
em processo, BrasilAPI falsa e Jev/LLM falsos. Os turnos passam pelo
`AgentService` como no worker; os turnos de sistema, pelos jobs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest
from conftest import Fakes, resultado_jev, settings_granatech
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.clt import regras
from saturday.agent.clt.mensagens import texto
from saturday.agent.coleta import hoje_operacao
from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.canais.base import OrigemCanal
from saturday.dados.modelos import (
    Alerta,
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Mensagem,
    Outbox,
    Recontato,
)
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.fontes.brasilapi import ErroBrasilAPI
from saturday.jobs import granatech as eventos_granatech
from saturday.jobs import recontatos as job_recontatos
from saturday.schemas import AgentReply, ChatRequest

# O cliente passa `timeout` ao `httpx`; o `TestClient` do simulador avisa.
pytestmark = pytest.mark.filterwarnings("ignore:You should not use the 'timeout' argument")

CPF = "00189004967"
CNPJ = "11.222.333/0001-81"
TELEFONE = "11987654321"
EMPRESA_OK = {
    "cnpj": "11222333000181",
    "razao_social": "PRIME TECH LTDA",
    "descricao_situacao_cadastral": "ATIVA",
    "data_inicio_atividade": "2015-03-01",
    "opcao_pelo_mei": False,
    "codigo_porte": 5,
}


class FakeBrasilAPI:
    def __init__(self) -> None:
        self.dados: dict[str, Any] | None = dict(EMPRESA_OK)
        self.erro = False
        self.chamadas = 0

    def buscar_empresa(self, cnpj: str, *, conversa_id: Any = None) -> dict[str, Any] | None:
        self.chamadas += 1
        if self.erro:
            raise ErroBrasilAPI("fora do ar")
        return self.dados


class Jornada:
    """Uma conversa de WhatsApp com o agente."""

    def __init__(
        self,
        servico: AgentService,
        fabrica: sessionmaker[Session],
        cliente: ClienteGranatech,
    ) -> None:
        self.servico = servico
        self.fabrica = fabrica
        self.cliente = cliente
        self.id = f"clt-{uuid.uuid4().hex[:10]}"

    def falar(self, mensagem: str) -> AgentReply:
        return self.servico.process_message(
            ChatRequest(
                conversation_id=self.id,
                message_id=f"wamid.{uuid.uuid4().hex}",
                message=mensagem,
            ),
            OrigemCanal(canal="whatsapp", telefone=TELEFONE, phone_number_id="100000000000001"),
        )

    def roteiro(self, *mensagens: str) -> AgentReply:
        resposta = None
        for mensagem in mensagens:
            resposta = self.falar(mensagem)
            assert resposta.status == "answered", (mensagem, resposta)
        assert resposta is not None
        return resposta

    def clt(self) -> dict[str, Any]:
        return dict(self.servico.estado_atual(self.servico.config(self.id)).get("clt") or {})

    def consulta(self) -> str:
        return str(self.clt()["consulta"])

    def evento_consulta(self, status: str) -> None:
        payload = {"tipo": "CONSULTA", "id_solicitacao": self.consulta(), "status": status}
        eventos_granatech.aplicar(self.fabrica, self.cliente, payload, self.servico)

    def ultima_saida(self) -> str:
        with abrir_sessao(self.fabrica) as sessao:
            conversa = sessao.scalars(
                select(Conversa).where(Conversa.conversation_id == self.id)
            ).one()
            return str(
                sessao.scalars(
                    select(Mensagem.conteudo)
                    .where(Mensagem.conversa_id == conversa.id, Mensagem.direcao == "saida")
                    .order_by(Mensagem.id.desc())
                ).first()
            )

    def conversa_uuid(self) -> uuid.UUID:
        with abrir_sessao(self.fabrica) as sessao:
            return sessao.scalars(
                select(Conversa.id).where(Conversa.conversation_id == self.id)
            ).one()


TRIAGEM_OK = ("Quero o empréstimo do trabalhador", "sim", "3 anos", "não", "não", "sim")
ATE_CONSENTIMENTO = (
    *TRIAGEM_OK,
    CNPJ,
    CPF,
    "Cliente de Teste da Silva",
    "15/05/1990",
    "masculino",
    "cliente@exemplo.com",
    "sim",
)


@pytest.fixture
def fakes_clt() -> Fakes:
    fakes = Fakes()
    fakes.jev.resultado = resultado_jev(publico="clt")
    return fakes


@pytest.fixture
def brasilapi() -> FakeBrasilAPI:
    return FakeBrasilAPI()


def _montar(
    fabrica: sessionmaker[Session],
    http: TestClient,
    fakes: Fakes,
    brasilapi: FakeBrasilAPI,
    **extras: Any,
) -> tuple[AgentService, ClienteGranatech]:
    settings = settings_granatech(**extras)
    cliente = ClienteGranatech(http, settings, fabrica, dormir=lambda _s: None)
    contexto = AgentContext(
        jev=fakes.jev,  # type: ignore[arg-type]
        llm=fakes.llm,  # type: ignore[arg-type]
        anexos=fakes.anexos,  # type: ignore[arg-type]
        granatech=cliente,
        brasilapi=brasilapi,  # type: ignore[arg-type]
        fabrica=fabrica,
        dominio_publico=settings.dominio_publico,
    )
    checkpointer = InMemorySaver()
    servico = AgentService(
        graph=build_graph(checkpointer),
        context=contexto,
        webhook=fakes.webhook,  # type: ignore[arg-type]
        settings=settings,
        checkpointer=checkpointer,
        fabrica=fabrica,
    )
    return servico, cliente


@pytest.fixture
def nova(
    fabrica: sessionmaker[Session],
    http_granatech: TestClient,
    fakes_clt: Fakes,
    brasilapi: FakeBrasilAPI,
) -> Any:
    def criar(**extras: Any) -> Jornada:
        servico, cliente = _montar(fabrica, http_granatech, fakes_clt, brasilapi, **extras)
        return Jornada(servico, fabrica, cliente)

    return criar


def nao_elegivel(chave: str) -> str:
    """Todo não elegível sai com o convite para a equipe rever as respostas."""

    return f"{texto(chave)}\n\n{texto('nao_elegivel_rever')}"


def _consultas(fabrica: sessionmaker[Session]) -> int:
    with abrir_sessao(fabrica) as sessao:
        return int(sessao.scalar(select(func.count()).select_from(ConsultaGranatech)) or 0)


def _ate_oferta(jornada: Jornada) -> AgentReply:
    resposta = jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    assert resposta.answer == texto("consultando")
    jornada.evento_consulta("SUCCESS")
    assert jornada.clt()["etapa"] == "escolha_vinculo"
    return jornada.roteiro("1")


# ---------------------------------------------------------------- aprovado


def test_jornada_aprovada_ate_a_oferta(nova: Any, fabrica: sessionmaker[Session]) -> None:
    jornada = nova()

    abertura = jornada.falar("Quero o empréstimo do trabalhador")
    assert "Vou usar os dados do seu emprego" in abertura.answer
    assert abertura.answer.endswith(texto("triagem_carteira"))

    resposta = jornada.roteiro(*ATE_CONSENTIMENTO[1:])
    assert resposta.answer == texto("consentimento")
    assert _consultas(fabrica) == 0

    resposta = jornada.falar("SIM")
    assert resposta.answer == texto("consultando")
    assert jornada.clt()["etapa"] == "consultando"
    with abrir_sessao(fabrica) as sessao:
        prova = sessao.scalars(select(Consentimento)).one()
        assert prova.tipo == "consulta"
        assert prova.resposta_literal == "SIM"
        assert prova.texto_mostrado == texto("consentimento")
        assert prova.cpf == CPF and prova.wamid and prova.versao

    # Pergunta durante a consulta vai para a FAQ; o resto espera.
    assert jornada.falar("e aí, já saiu").answer == texto("aguardando_consulta")

    jornada.evento_consulta("SUCCESS")
    lista = jornada.ultima_saida()
    assert lista.startswith(texto("escolher_vinculo"))
    assert "1. Prime Tech LTDA, margem de R$ 1.500,00" in lista
    assert "2. EMPREGADOR MOCK LTDA" in lista

    oferta = jornada.falar("1").answer
    assert oferta.startswith(texto("aviso_teto", teto="6.999,00"))
    assert "Boa notícia, Cliente!" in oferta and "Super Proteção" in oferta
    dados = jornada.clt()["oferta"]
    assert Decimal(dados["liberado"]) <= Decimal("6999")
    assert dados["numero_parcelas"] == 48 and dados["seguro_aplicado"] is True

    # Evento repetido não fala de novo.
    jornada.evento_consulta("SUCCESS")
    assert jornada.ultima_saida() == oferta

    aceite = jornada.falar("quero sim")
    assert aceite.status == "handoff"
    assert aceite.handoff_reason == "aceite_clt"
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Consentimento)) == 1


def test_pedidos_depois_da_oferta_e_limite(nova: Any) -> None:
    jornada = nova()
    _ate_oferta(jornada)

    # A dev só tem produtos com seguro.
    assert jornada.falar("quero sem seguro").answer == texto("sem_seguro_indisponivel")
    resposta = jornada.falar("e em 24 vezes")
    assert resposta.answer == texto("prazo_indisponivel", prazos="17, 25, 36, 48")
    resposta = jornada.falar("em 25 parcelas")
    assert jornada.clt()["oferta"]["numero_parcelas"] == 25
    assert "25 parcelas" in resposta.answer
    assert jornada.falar("parcela de R$ 2.000").answer == texto(
        "parcela_acima_margem", margem="1.500,00"
    )
    jornada.falar("parcela de 200")
    assert Decimal(jornada.clt()["oferta"]["valor_parcela"]) == Decimal("200")

    for _ in range(3):
        jornada.falar("em 36 parcelas")
    assert jornada.clt()["novas_simulacoes"] == 5
    fim = jornada.falar("em 17 parcelas")
    assert fim.status == "handoff" and fim.handoff_reason == "limite_simulacoes"


# ---------------------------------------------------------------- triagem


@pytest.mark.parametrize(
    ("respostas", "chave"),
    [
        (("não",), "nao_elegivel_carteira"),
        (("sim", "2 anos", "sim"), "nao_elegivel_contrato_especial"),
        (("sim", "2 anos", "não", "sim"), "nao_elegivel_granatech"),
        (("sim", "2 anos", "não", "não", "não"), "nao_elegivel_funcionarios"),
    ],
)
def test_reprovado_na_triagem(nova: Any, respostas: tuple[str, ...], chave: str) -> None:
    jornada = nova()
    resposta = jornada.roteiro("Quero o crédito CLT", *respostas)
    assert resposta.answer == nao_elegivel(chave)
    assert jornada.clt()["etapa"] == "nao_elegivel"
    # Depois de encerrado, só a FAQ.
    jornada.falar("posso tentar de novo?")
    assert jornada.clt()["etapa"] == "nao_elegivel"


def test_tempo_de_casa_curto_pede_optin_e_recontata(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    resposta = jornada.roteiro("Quero o crédito CLT", "sim", "8 meses")
    quando = regras.data_recontato_tempo_casa(8, hoje_operacao())
    data = quando.strftime("%d/%m/%Y")
    assert resposta.answer == texto("recontato_tempo_casa", data=data)

    assert jornada.falar("sim").answer == texto("optin_confirmado", data=data)
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalars(select(Recontato.motivo)).one() == "tempo_casa"
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == jornada.id)
        ).one()
        assert conversa.marketing == "opt_in"

    # Antes da data, nada; na data, o modelo sai e a jornada recomeça.
    assert job_recontatos.disparar(fabrica, jornada.servico) == 0
    futuro = datetime.now(UTC) + timedelta(days=200)
    assert job_recontatos.disparar(fabrica, jornada.servico, futuro) == 1
    assert jornada.ultima_saida() == "[modelo recontato_tempo_casa]"
    with abrir_sessao(fabrica) as sessao:
        payload = sessao.scalars(select(Outbox.payload).order_by(Outbox.id.desc())).first()
        assert payload is not None and payload["modelo"] == "recontato_tempo_casa"
    assert jornada.clt() == {"etapa": "abertura"}
    assert "Vou usar os dados do seu emprego" in jornada.falar("oi, já completei").answer


def test_tempo_de_casa_sem_optin_nao_recontata(nova: Any, fabrica: sessionmaker[Session]) -> None:
    jornada = nova()
    jornada.roteiro("Quero o crédito CLT", "sim", "8 meses")
    assert jornada.falar("não").answer == texto("optin_recusado")
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Recontato)) == 0


def test_nao_quero_receber_grava_optout(nova: Any, fabrica: sessionmaker[Session]) -> None:
    jornada = nova()
    jornada.roteiro("Quero o crédito CLT", "sim", "8 meses", "sim")
    assert jornada.falar("Não quero receber").answer == texto("optout")
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == jornada.id)
        ).one()
        assert conversa.marketing == "opt_out"
    futuro = datetime.now(UTC) + timedelta(days=200)
    job_recontatos.disparar(fabrica, jornada.servico, futuro)
    assert jornada.ultima_saida() == texto("optout")


def test_dois_erros_no_mesmo_dado_vao_para_handoff(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro("Quero o crédito CLT", "sim")
    assert jornada.falar("faz um tempinho").answer == texto("repetir_tempo_casa")
    resposta = jornada.falar("bastante")
    assert resposta.status == "handoff" and resposta.handoff_reason == "dado_invalido_repetido"


def test_pergunta_no_meio_da_triagem_vai_para_a_faq(nova: Any, fakes_clt: Fakes) -> None:
    jornada = nova()
    jornada.roteiro("Quero o crédito CLT")
    resposta = jornada.falar("o que é carteira assinada?")
    assert resposta.answer == fakes_clt.llm.resposta.resposta
    assert jornada.clt()["passo"] == "carteira"


# ---------------------------------------------------------------- empresa


@pytest.mark.parametrize(
    "extras",
    [
        {"descricao_situacao_cadastral": "BAIXADA"},
        {"data_inicio_atividade": (date.today() - timedelta(days=200)).isoformat()},
        {"opcao_pelo_mei": True},
        {"codigo_porte": 1},
        {"razao_social": "ACME EM RECUPERACAO JUDICIAL"},
    ],
)
def test_empresa_reprovada(nova: Any, brasilapi: FakeBrasilAPI, extras: dict[str, Any]) -> None:
    brasilapi.dados = {**EMPRESA_OK, **extras}
    jornada = nova()
    resposta = jornada.roteiro(*TRIAGEM_OK, CNPJ)
    assert resposta.answer == nao_elegivel("nao_elegivel_empresa")


def test_brasilapi_fora_do_ar_vai_para_handoff(nova: Any, brasilapi: FakeBrasilAPI) -> None:
    brasilapi.erro = True
    jornada = nova()
    jornada.roteiro(*TRIAGEM_OK)
    resposta = jornada.falar(CNPJ)
    assert resposta.status == "handoff" and resposta.handoff_reason == "brasilapi_indisponivel"


def test_so_o_nome_da_empresa_pede_o_cnpj(nova: Any, brasilapi: FakeBrasilAPI) -> None:
    jornada = nova()
    resposta = jornada.roteiro(*TRIAGEM_OK, "Prime Tech")
    assert resposta.answer == texto("cnpj_invalido")
    assert brasilapi.chamadas == 0


# ---------------------------------------------------------------- consentimento


@pytest.mark.parametrize(
    "texto_cliente", ["ok", "pode ver", "simulação", "sim? não sei", "não, sim depois"]
)
def test_nenhuma_consulta_sem_consentimento(
    nova: Any,
    fabrica: sessionmaker[Session],
    simulador_granatech: ModuleType,
    texto_cliente: str,
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO)
    jornada.falar(texto_cliente)
    assert jornada.clt()["etapa"] == "consentimento"
    assert _consultas(fabrica) == 0
    assert not simulador_granatech.CONSULTAS
    with abrir_sessao(fabrica) as sessao:
        assert sessao.scalar(select(func.count()).select_from(Consentimento)) == 0


def test_celular_negado_pede_outro(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO[:-1])
    assert jornada.falar("não").answer == texto("pedir_celular")
    assert jornada.falar("(21) 99876-5432").answer == texto("consentimento")
    assert jornada.clt()["dados"]["celular"] == "21998765432"


def test_termo_que_falha_manda_o_link(nova: Any, http_granatech: TestClient) -> None:
    http_granatech.post(
        "/admin/falha",
        json={"rota": "/termo-consentimento", "status": 500},
    )
    jornada = nova()
    resposta = jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    assert texto("termo_link", link="").strip() in resposta.answer
    assert "http" in resposta.answer.split(":", 1)[1]


def test_termo_pendente_reenvia_o_link(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    resposta = jornada.servico.continuar(jornada.id, "termo_pendente")
    assert resposta is not None and resposta.answer.startswith(texto("termo_link", link="").strip())


# ---------------------------------------------------------------- consulta


def test_sem_margem(nova: Any) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    jornada.evento_consulta("NO_MARGIN")
    assert jornada.ultima_saida() == nao_elegivel("nao_elegivel_sem_margem")
    assert jornada.clt()["etapa"] == "nao_elegivel"


def test_status_de_erro_vai_para_handoff(nova: Any, fabrica: sessionmaker[Session]) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    jornada.evento_consulta("USED")
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == jornada.id)
        ).one()
        assert conversa.atendimento == "handoff"


def test_mulher_de_55_tem_prazo_limitado(
    nova: Any, simulador_granatech: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Faz 57 daqui a 20 meses: só o prazo de 17 cabe.
    nascimento = regras.somar_meses(hoje_operacao(), -(57 * 12) + 20)
    monkeypatch.setitem(simulador_granatech.PESSOA, "birth_date", nascimento.isoformat())
    monkeypatch.setitem(simulador_granatech.PESSOA, "gender", "F")
    jornada = nova()
    jornada.roteiro(
        *TRIAGEM_OK,
        CNPJ,
        CPF,
        "Cliente de Teste",
        nascimento.strftime("%d/%m/%Y"),
        "feminino",
        "cliente@exemplo.com",
        "sim",
        "SIM",
    )
    jornada.evento_consulta("SUCCESS")
    jornada.falar("2")
    assert jornada.clt()["oferta"]["numero_parcelas"] == 17


def test_divergencia_pos_consulta_vale_a_granatech(
    nova: Any, simulador_granatech: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Informou homem de 36 anos; a Granatech diz mulher perto do limite.
    nascimento = regras.somar_meses(hoje_operacao(), -(57 * 12) + 10)
    monkeypatch.setitem(simulador_granatech.PESSOA, "birth_date", nascimento.isoformat())
    monkeypatch.setitem(simulador_granatech.PESSOA, "gender", "F")
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    jornada.evento_consulta("SUCCESS")
    assert jornada.ultima_saida() == nao_elegivel("nao_elegivel_idade")


def test_idade_sem_prazo_nao_segue(nova: Any) -> None:
    jornada = nova()
    resposta = jornada.roteiro(*TRIAGEM_OK, CNPJ, CPF, "Ana Souza", "01/01/1966", "feminino")
    assert resposta.answer == nao_elegivel("nao_elegivel_idade")


def test_reaproveita_consulta_pronta_do_mesmo_cpf(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    primeira = nova()
    _ate_oferta(primeira)
    segunda = nova()
    resposta = segunda.roteiro(*ATE_CONSENTIMENTO, "SIM")
    assert resposta.answer.startswith(texto("escolher_vinculo"))
    assert _consultas(fabrica) == 1


# ---------------------------------------------------------------- cota e recontato


def test_cota_esgotada_recontata_e_desiste_depois_de_3(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova(granatech_cota_diaria=0)
    resposta = jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    assert resposta.answer == texto("cota_esgotada")
    assert jornada.falar("ok").answer == texto("aguardando_recontato")

    futuro = datetime.now(UTC) + timedelta(days=10)
    for tentativa in range(1, 4):
        assert job_recontatos.disparar(fabrica, jornada.servico, futuro) == 1
        with abrir_sessao(fabrica) as sessao:
            assert (
                sessao.scalars(select(Recontato.tentativas).order_by(Recontato.id.desc())).first()
                == tentativa
            )
    assert job_recontatos.disparar(fabrica, jornada.servico, futuro) == 1
    with abrir_sessao(fabrica) as sessao:
        conversa = sessao.scalars(
            select(Conversa).where(Conversa.conversation_id == jornada.id)
        ).one()
        assert conversa.atendimento == "handoff"
    assert _consultas(fabrica) == 0


def test_recontato_com_cota_volta_e_consulta(nova: Any, fabrica: sessionmaker[Session]) -> None:
    jornada = nova(granatech_cota_diaria=0)
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    jornada.servico.context.granatech._settings.granatech_cota_diaria = 5  # type: ignore[union-attr]
    job_recontatos.disparar(fabrica, jornada.servico, datetime.now(UTC) + timedelta(days=2))
    assert jornada.ultima_saida() == texto("consultando")
    assert _consultas(fabrica) == 1


# ---------------------------------------------------------------- conversa com humano e flag


def test_evento_com_conversa_assumida_vira_alerta(
    nova: Any, fabrica: sessionmaker[Session]
) -> None:
    jornada = nova()
    jornada.roteiro(*ATE_CONSENTIMENTO, "SIM")
    with abrir_sessao(fabrica) as sessao:
        sessao.execute(
            update(Conversa)
            .where(Conversa.conversation_id == jornada.id)
            .values(atendimento="assumida")
        )
    jornada.evento_consulta("SUCCESS")
    assert jornada.clt()["etapa"] == "consultando"
    with abrir_sessao(fabrica) as sessao:
        alerta = sessao.scalars(select(Alerta).where(Alerta.tipo == "evento_com_humano")).one()
        assert alerta.detalhe == {"evento": "consulta_pronta"}


def test_flag_desligada_mantem_o_comportamento(service: AgentService, fakes: Fakes) -> None:
    fakes.jev.resultado = resultado_jev(publico="clt")
    resposta = service.process_message(
        ChatRequest(conversation_id="sem-clt", message="Quero o crédito CLT")
    )
    assert resposta.answer == fakes.llm.resposta.resposta
    assert not service.estado_atual(service.config("sem-clt")).get("clt")
