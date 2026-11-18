"""Nós do grafo. Cada nó tem uma responsabilidade só."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from saturday.agent.clt import leitura
from saturday.agent.clt.turno import reais
from saturday.agent.coleta import (
    hoje_operacao,
    ler_renda,
    normalizar_uf,
    parse_data_nascimento,
)
from saturday.agent.context import AgentContext
from saturday.agent.icred.nos import extrato_novo
from saturday.agent.state import AgentState, ultima_mensagem_agente
from saturday.agent.textos import (
    CONSENTIMENTO_C6,
    CONSENTIMENTO_C6_REPETIR,
    MENSAGEM_BOAS_VINDAS,
    MENSAGEM_EXTRATO_ILEGIVEL,
    MENSAGEM_EXTRATO_INCORRETO,
    MENSAGEM_EXTRATO_MES_ERRADO,
    MENSAGEM_NAO_ENTENDI,
    MENSAGEM_RECUSA,
    MENSAGEM_SEM_TEXTO,
    MENSAGENS_FALHA_CALCULO,
    OFERTA_CONTRATO_NOVO,
    PERGUNTA_CPF,
    PERGUNTA_CPF_INVALIDO,
    PERGUNTA_DATA,
    PERGUNTA_DATA_INVALIDA,
    PERGUNTA_RENDA,
    PERGUNTA_RENDA_INVALIDA,
    PERGUNTA_UF,
    PERGUNTA_UF_INVALIDA,
    VERSAO_CONSENTIMENTO_C6,
    chave_handoff,
    mensagem_handoff,
)
from saturday.bancos.c6 import regras as regras_c6
from saturday.bancos.c6.cliente import ErroC6, PedidoSimulacao
from saturday.dados import consentimentos
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.portabilidade import calculo, mensagem
from saturday.portabilidade import hiscon as hiscon_mod
from saturday.portabilidade.regras import IDADE_WEBPLUS, PRAZO_C6
from saturday.portabilidade.util import parse_data
from saturday.services.anexos import AnexoInvalido
from saturday.settings import HISTORY_MAX_MESSAGES, JEV_INTENT_THRESHOLD, TZ_OPERACAO

logger = logging.getLogger(__name__)

CONSENTIMENTO_SIMULACAO_C6 = "simulacao_c6"


def _historico(state: AgentState) -> list[dict[str, str]]:
    mensagens = state.get("messages") or []
    historico = []
    for mensagem_atual in mensagens[-HISTORY_MAX_MESSAGES:]:
        role = "assistant" if isinstance(mensagem_atual, AIMessage) else "user"
        conteudo = mensagem_atual.content
        if not isinstance(conteudo, str):
            conteudo = str(conteudo)
        if conteudo.strip():
            historico.append({"role": role, "content": conteudo})
    return historico


def _resumo_portabilidade(state: AgentState) -> str | None:
    resultado = state.get("portability_result")
    if not resultado or not resultado.get("ok"):
        return None
    contratos = resultado.get("contratos") or []
    elegiveis = [c for c in contratos if c.get("elegivel")]
    if not elegiveis:
        return None
    faixa = resultado.get("troco_faixa") or {}
    linhas = [
        f"Contratos com portabilidade para o C6: {len(elegiveis)}.",
        "Sobra aproximada total: "
        f"de R$ {mensagem.formatar_valor(faixa.get('min'))} a "
        f"R$ {mensagem.formatar_valor(faixa.get('max'))}.",
    ]
    for contrato in elegiveis:
        faixa_contrato = contrato.get("troco_faixa") or {}
        linhas.append(
            f"- {contrato.get('banco')}: de R$ "
            f"{mensagem.formatar_valor(faixa_contrato.get('min'))} a R$ "
            f"{mensagem.formatar_valor(faixa_contrato.get('max'))}."
        )
    return "\n".join(linhas)


def _pedido(pergunta: str, aguardando: str, chave: str) -> dict[str, Any]:
    return {
        "status": "answered",
        "answer": pergunta,
        "chave_mensagem": chave,
        "aguardando": aguardando,
        "tentativas_coleta": 0,
        "needs_human": False,
        "messages": [AIMessage(content=pergunta)],
    }


def _resultado_falha(extrato: dict[str, Any], motivo: str, prazo: int = PRAZO_C6) -> dict[str, Any]:
    return {
        "ok": False,
        "motivo": motivo,
        "prazo": prazo,
        "beneficio_bloqueado": extrato.get("liberadoParaEmprestimo") is False,
        "alerta_webplus": False,
        "troco_total": 0.0,
        "troco_faixa": {"min": 0.0, "max": 0.0},
        "contratos": [],
    }


def pedir_texto(state: AgentState) -> dict[str, Any]:
    """Mensagem sem texto que dê para ler: pede ao cliente que escreva."""

    return {
        "status": "answered",
        "answer": MENSAGEM_SEM_TEXTO,
        "chave_mensagem": "textos:sem_texto",
        "needs_human": False,
        "messages": [AIMessage(content=MENSAGEM_SEM_TEXTO)],
    }


def _sem_jornada(state: AgentState) -> bool:
    """Nenhuma jornada (CLT ou INSS) em curso."""

    return (
        not (state.get("clt") or {}).get("etapa")
        and not state.get("hiscon")
        and not state.get("oferta_pendente")
        and not state.get("aguardando")
    )


def _entra_no_clt(state: AgentState, publico: str, contexto: AgentContext) -> bool:
    """CLT com a Granatech ligada e nenhuma jornada em curso."""

    return publico == "clt" and contexto.granatech is not None and _sem_jornada(state)


def classify_intent(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Classifica intenção e público da mensagem pelo Jev; erro do Jev segue para o LLM."""

    try:
        resultado = runtime.context.jev.classify(
            state.get("user_message", ""),
            bool(state.get("oferta_pendente")),
            oferta=ultima_mensagem_agente(state),
        )
    except Exception:
        # Erro do Jev não interrompe o atendimento: segue para o LLM.
        return {}

    intent = resultado.intent
    pediu_humano = resultado.pediu_humano
    if pediu_humano:
        intent = "humano"
    elif intent == "humano":
        intent = "duvida"
    elif resultado.saudou and _sem_jornada(state):
        # Cumprimento sem jornada: boas-vindas fixas, sem LLM.
        intent = "saudacao"
    elif intent == "saudacao":
        # Abaixo do limiar ou no meio de uma jornada: segue como dúvida.
        intent = "duvida"

    publico = resultado.publico
    if (
        publico == "indefinido"
        or resultado.probabilidade("publico", publico) < JEV_INTENT_THRESHOLD
    ):
        # Só um público dito com clareza troca o anterior; negar ("não sou
        # servidor") cai em `indefinido` pelo critério do Jev.
        publico = state.get("publico") or "indefinido"

    resposta_oferta = None
    if state.get("oferta_pendente"):
        if resultado.aceitou_oferta:
            resposta_oferta = "aceita"
        elif resultado.recusou_oferta:
            resposta_oferta = "recusa"
        else:
            resposta_oferta = "duvida"

    atualizacao: dict[str, Any] = {
        "intent": intent,
        # A confiança fica só para diagnóstico; a decisão usa as probabilidades.
        "intent_confidence": resultado.intent_confidence,
        "publico": publico,
        "resposta_oferta": resposta_oferta,
    }
    if _entra_no_clt(state, publico, runtime.context):
        atualizacao["clt"] = {"etapa": "abertura"}
    if pediu_humano:
        atualizacao.update({"needs_human": True, "handoff_reason": "pediu_humano"})
    elif resposta_oferta == "aceita":
        c6_novo = state.get("c6_novo") or {}
        ofertado = c6_novo.get("situacao") == "ofertado"
        motivo = "aceitou_contrato_novo" if ofertado else "aceitou_portabilidade"
        atualizacao.update({"needs_human": True, "handoff_reason": motivo})
        if ofertado:
            # O atendente lê no painel as condições que o cliente aceitou.
            atualizacao["c6_novo"] = {**c6_novo, "situacao": "aceito"}
    return atualizacao


def generate_answer(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Responde a dúvida pelo LLM, ancorado na FAQ; sem resposta segura, vai para handoff."""

    conhecimento = runtime.context.conhecimento
    trechos = conhecimento.buscar(state.get("user_message", "")) if conhecimento else []
    try:
        resposta = runtime.context.llm.responder(
            _historico(state),
            _resumo_portabilidade(state),
            trechos,
        )
    except Exception:
        return {
            "status": "in_progress",
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    if not resposta.resolvido or not resposta.resposta:
        tentativas = int(state.get("tentativas_resposta") or 0) + 1
        if tentativas < 2 and _sem_jornada(state):
            # Primeira sem FAQ fora de jornada: o cliente reformula antes da equipe.
            return {
                "status": "answered",
                "answer": MENSAGEM_NAO_ENTENDI,
                "chave_mensagem": "textos:nao_entendi",
                "tentativas_resposta": tentativas,
                "messages": [AIMessage(content=MENSAGEM_NAO_ENTENDI)],
            }
        return {
            "status": "in_progress",
            "needs_human": True,
            "handoff_reason": "sem_resposta",
            "tentativas_resposta": 0,
        }

    return {
        "status": "answered",
        "answer": resposta.resposta,
        # Escrita pelo modelo: sem chave de mensagem fixa (decisão 0018).
        "chave_mensagem": None,
        "tentativas_resposta": 0,
        "messages": [AIMessage(content=resposta.resposta)],
    }


def boas_vindas(state: AgentState) -> dict[str, Any]:
    """Primeira mensagem sem jornada: apresenta o atendimento."""

    return {
        "status": "answered",
        "answer": MENSAGEM_BOAS_VINDAS,
        "chave_mensagem": "textos:boas_vindas",
        "needs_human": False,
        "tentativas_resposta": 0,
        "messages": [AIMessage(content=MENSAGEM_BOAS_VINDAS)],
    }


def handoff(state: AgentState) -> dict[str, Any]:
    """Passa a conversa para a equipe com o motivo e avisa o cliente."""

    motivo = state.get("handoff_reason") or "sem_resposta"
    anterior = state.get("answer")
    resposta = mensagem_handoff(motivo, anterior)
    # A fala que o nó anterior preparou mantém a chave dela.
    chave = state.get("chave_mensagem") if anterior else f"handoff:{motivo}"
    return {
        "status": "handoff",
        "needs_human": True,
        "handoff_reason": motivo,
        "answer": resposta,
        "chave_mensagem": chave_handoff(chave, resposta),
        "handoff_em": datetime.now(ZoneInfo(TZ_OPERACAO)).isoformat(),
        "messages": [AIMessage(content=resposta)],
    }


def decline_offer(state: AgentState) -> dict[str, Any]:
    """Cliente recusou a oferta do INSS: agradece e encerra a oferta."""

    return {
        "status": "answered",
        "answer": MENSAGEM_RECUSA,
        "chave_mensagem": "textos:recusa",
        "oferta_pendente": False,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=MENSAGEM_RECUSA)],
    }


def _perguntar_extrato(state: AgentState, pergunta: str, chave: str) -> dict[str, Any]:
    tentativas = int(state.get("tentativas_extrato") or 0) + 1
    if tentativas >= 2:
        return {
            "tentativas_extrato": tentativas,
            "needs_human": True,
            "handoff_reason": "extrato_ilegivel_repetido",
        }
    return {
        "tentativas_extrato": tentativas,
        "status": "answered",
        "answer": pergunta,
        "chave_mensagem": chave,
        "needs_human": False,
        "messages": [AIMessage(content=pergunta)],
    }


def read_statement(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Lê o extrato do INSS (foto ou PDF) pelo modelo de visão e valida."""

    try:
        anexos = runtime.context.anexos.carregar_anexos(state.get("attachments") or [])
    except AnexoInvalido:
        return _perguntar_extrato(
            state, runtime.context.anexos.mensagem_anexo_invalido(), "anexos:anexo_invalido"
        )

    try:
        dados = runtime.context.llm.ler_extrato(anexos)
        extrato = hiscon_mod.normalizar_extrato(dados)
    except Exception:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_ILEGIVEL, "textos:extrato_ilegivel")

    status = hiscon_mod.validar_extrato(extrato, hoje_operacao())
    if status == hiscon_mod.STATUS_NAO_HISCON:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_INCORRETO, "textos:extrato_incorreto")
    if status == hiscon_mod.STATUS_ILEGIVEL:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_ILEGIVEL, "textos:extrato_ilegivel")
    if status == hiscon_mod.STATUS_MES_ERRADO:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_MES_ERRADO, "textos:extrato_mes_errado")

    dados_extrato = extrato.model_dump()
    if status == hiscon_mod.STATUS_CONFERENCIA_FALHOU:
        return {
            "portability_result": _resultado_falha(dados_extrato, "hiscon_nao_conferiu"),
            "needs_human": True,
            "handoff_reason": "hiscon_nao_conferiu",
        }
    if status == hiscon_mod.STATUS_ESPECIE_NAO_ATENDIDA:
        return {
            "portability_result": _resultado_falha(dados_extrato, "especie_nao_atendida"),
            "answer": mensagem.MENSAGEM_ESPECIE_NAO_ATENDIDA,
            "chave_mensagem": "inss:especie_nao_atendida",
            "needs_human": True,
            "handoff_reason": "especie_nao_atendida",
        }

    return {
        "hiscon": dados_extrato,
        "hiscon_recebido_em": datetime.now(ZoneInfo(TZ_OPERACAO)).isoformat(),
        "tentativas_extrato": 0,
        "portability_result": None,
        "c6_novo": None,
        "oferta_pendente": False,
        "resposta_oferta": None,
        "icred": extrato_novo(state.get("icred")),
    }


def check_customer_data(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Confere se faltam dados do cliente (nascimento, UF) e o SIM da simulação no C6."""

    cliente: dict[str, Any] = dict(state.get("cliente") or {})
    hoje = hoje_operacao()
    idade = calculo.idade_em_anos(cliente.get("data_nascimento"), hoje)

    if idade is None:
        return _pedido(PERGUNTA_DATA, "data_nascimento", "textos:pergunta_data")

    uf = normalizar_uf(cliente.get("uf"))
    if uf is not None:
        cliente["uf"] = uf

    if idade >= IDADE_WEBPLUS and uf is None:
        return _pedido(PERGUNTA_UF, "uf", "textos:pergunta_uf")

    extrato = state.get("hiscon") or {}
    cpf_extrato = leitura.cpf(str(extrato.get("cpf") or ""))
    if runtime.context.c6_ativo and cpf_extrato and cliente.get("cpf") not in (None, cpf_extrato):
        # Extrato de outro titular: a autorização e a renda do anterior não valem.
        cliente.pop("c6_autorizado", None)
        cliente.pop("renda", None)
        cliente["cpf"] = cpf_extrato

    # Com o C6 ligado, o titular decide uma vez por conversa se autoriza a simulação.
    # O pedido só sai se o extrato permite simular: sem isso, nada de CPF nem de SIM.
    pede = runtime.context.c6_ativo and "c6_autorizado" not in cliente
    if pede and _pedido_c6(cliente, extrato) is not None:
        cpf = cliente.get("cpf") or cpf_extrato
        if cpf is None:
            return {**_pedido(PERGUNTA_CPF, "cpf", "textos:pergunta_cpf"), "cliente": cliente}
        cliente["cpf"] = cpf
        pedido = _pedido(CONSENTIMENTO_C6, "consentimento_c6", "textos:consentimento_c6")
        return {**pedido, "cliente": cliente}

    # A simulação pede a renda: vem do extrato; se a leitura não achou, o cliente diz.
    simula = runtime.context.c6 is not None and cliente.get("c6_autorizado") is True
    if simula and not state.get("c6_novo") and _pedido_c6(cliente, extrato) is not None:
        if extrato.get("baseCalculo"):
            cliente["renda"] = float(extrato["baseCalculo"])
        if not cliente.get("renda"):
            return {**_pedido(PERGUNTA_RENDA, "renda", "textos:pergunta_renda"), "cliente": cliente}

    return {
        "status": "in_progress",
        "cliente": cliente,
        "aguardando": None,
        "tentativas_coleta": 0,
    }


def _falha_coleta(state: AgentState, pergunta: str, chave: str) -> dict[str, Any]:
    tentativas = int(state.get("tentativas_coleta") or 0) + 1
    if tentativas >= 2:
        return {
            "tentativas_coleta": tentativas,
            "needs_human": True,
            "handoff_reason": "dados_cliente_nao_informados",
        }
    return {
        "tentativas_coleta": tentativas,
        "status": "answered",
        "answer": pergunta,
        "chave_mensagem": chave,
        "needs_human": False,
        "messages": [AIMessage(content=pergunta)],
    }


def _sem_c6(
    state: AgentState, cliente: dict[str, Any], pergunta: str, chave: str
) -> dict[str, Any]:
    """Repete a pergunta uma vez; na segunda, segue só com a portabilidade."""

    if int(state.get("tentativas_coleta") or 0) >= 1:
        cliente["c6_autorizado"] = False
        return {"cliente": cliente, "tentativas_coleta": 0, "aguardando": None}
    return _falha_coleta(state, pergunta, chave)


def collect_customer_data(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Recebe o dado pedido (nascimento, UF, CPF, SIM do C6) e valida em código."""

    aguardando = state.get("aguardando")
    cliente: dict[str, Any] = dict(state.get("cliente") or {})
    texto = state.get("user_message", "")

    if aguardando == "data_nascimento":
        dados = parse_data_nascimento(texto, hoje_operacao())
        if dados is None:
            return _falha_coleta(state, PERGUNTA_DATA_INVALIDA, "textos:pergunta_data_invalida")
        data_iso, _ = dados
        cliente["data_nascimento"] = data_iso
        return {
            "cliente": cliente,
            "tentativas_coleta": 0,
            "aguardando": None,
        }

    if aguardando == "uf":
        uf = normalizar_uf(texto)
        if uf is None:
            return _falha_coleta(state, PERGUNTA_UF_INVALIDA, "textos:pergunta_uf_invalida")
        cliente["uf"] = uf
        return {
            "cliente": cliente,
            "tentativas_coleta": 0,
            "aguardando": None,
        }

    if aguardando == "renda":
        renda = ler_renda(texto)
        if renda is None:
            if int(state.get("tentativas_coleta") or 0) >= 1:
                # Sem renda não há simulação: segue só com a portabilidade.
                return {
                    "c6_novo": {"situacao": "sem_oferta"},
                    "tentativas_coleta": 0,
                    "aguardando": None,
                }
            return _falha_coleta(state, PERGUNTA_RENDA_INVALIDA, "textos:pergunta_renda_invalida")
        cliente["renda"] = renda
        return {"cliente": cliente, "tentativas_coleta": 0, "aguardando": None}

    if aguardando == "cpf":
        cpf = leitura.cpf(texto)
        if cpf is None:
            return _sem_c6(state, cliente, PERGUNTA_CPF_INVALIDO, "textos:pergunta_cpf_invalido")
        cliente["cpf"] = cpf
        return {"cliente": cliente, "tentativas_coleta": 0, "aguardando": None}

    if aguardando == "consentimento_c6":
        # Regra 3: o SIM só vale como resposta ao pedido. Se outra fala entrou
        # no meio (extrato recusado, mensagem vazia), o pedido é refeito.
        mostrado = ultima_mensagem_agente(state)
        if mostrado not in (CONSENTIMENTO_C6, CONSENTIMENTO_C6_REPETIR):
            return _pedido(CONSENTIMENTO_C6, "consentimento_c6", "textos:consentimento_c6")
        if leitura.consentiu(texto):
            # Regra 3: a prova é gravada antes de qualquer simulação.
            ref = state.get("conversa_ref")
            consentimentos.gravar_prova(
                runtime.context.fabrica,
                conversa_id=uuid.UUID(ref) if ref else None,
                tipo=CONSENTIMENTO_SIMULACAO_C6,
                texto_mostrado=mostrado,
                versao=VERSAO_CONSENTIMENTO_C6,
                resposta_literal=texto,
                wamid=state.get("message_id"),
                cpf=cliente["cpf"],
            )
            cliente["c6_autorizado"] = True
        elif leitura.NEGACAO.search(texto):
            cliente["c6_autorizado"] = False
        else:
            return _sem_c6(
                state, cliente, CONSENTIMENTO_C6_REPETIR, "textos:consentimento_c6_repetir"
            )
        return {"cliente": cliente, "tentativas_coleta": 0, "aguardando": None}

    return {}


def _pedido_c6(
    cliente: dict[str, Any], extrato: dict[str, Any]
) -> tuple[int, Decimal | None, Decimal, date] | None:
    """Prazo, teto, parcela e nascimento do pedido; ``None`` quando não dá para simular."""

    nascimento = parse_data(cliente.get("data_nascimento"))
    idade = calculo.idade_em_anos(cliente.get("data_nascimento"), hoje_operacao())
    margem = extrato.get("margemDisponivel")
    if nascimento is None or idade is None or not margem or not extrato.get("numeroBeneficio"):
        return None
    if (extrato.get("margemExtrapolada") or 0) > 0:
        return None
    faixa = regras_c6.prazo_e_teto(idade)
    parcela = regras_c6.parcela_do_contrato_novo(Decimal(str(margem)))
    if faixa is None or parcela is None:
        return None
    return faixa[0], faixa[1], parcela, nascimento


def _contrato_novo(state: AgentState, contexto: AgentContext) -> dict[str, Any] | None:
    """Condição de contrato novo escolhida em código, ou ``None`` sem oferta."""

    cliente = state.get("cliente") or {}
    extrato = state.get("hiscon") or {}
    cpf = cliente.get("cpf")
    renda = cliente.get("renda")
    limites = _pedido_c6(cliente, extrato)
    if contexto.c6 is None or limites is None or not (cpf and renda):
        return None
    if leitura.cpf(str(extrato.get("cpf") or "")) not in (None, cpf):
        # O SIM é do titular do CPF: não simula com o benefício de outra pessoa.
        return None
    prazo, teto, parcela, nascimento = limites

    ref = state.get("conversa_ref")
    conversa_id = uuid.UUID(ref) if ref else None
    with abrir_sessao(contexto.fabrica) as sessao:
        provado = consentimentos.existe_prova(
            sessao, conversa_id=conversa_id, tipo=CONSENTIMENTO_SIMULACAO_C6, cpf=cpf
        )
    if not provado:
        # Regra 3: nenhuma simulação sem o SIM gravado para este CPF.
        logger.error("c6_simulacao_sem_consentimento")
        return None

    pedido = PedidoSimulacao(
        operacao="NOVA",
        cpf=cpf,
        beneficio=extrato["numeroBeneficio"],
        nascimento=nascimento,
        renda=Decimal(str(renda)),
        parcelas=prazo,
        valor_parcela=parcela,
    )
    try:
        condicoes = contexto.c6.simular(pedido, conversa_id=conversa_id)
    except ErroC6 as erro:
        logger.warning("c6_simulacao_falhou status=%s", erro.status)
        return None
    escolhida = regras_c6.escolher(condicoes, prazo=prazo, parcela=parcela, teto=teto)
    if escolhida is None:
        return None
    return {
        "valor": str(escolhida.valor_cliente),
        "parcela": str(escolhida.parcela),
        "parcelas": escolhida.parcelas,
        "taxa": str(escolhida.taxa_mensal),
        "convenio": escolhida.convenio,
        "produto": escolhida.produto,
    }


def simulate_c6(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Simula o contrato novo no C6 e, havendo condição, monta a oferta fixa."""

    oferta = _contrato_novo(state, runtime.context)
    if oferta is None:
        return {"c6_novo": {"situacao": "sem_oferta"}}
    resposta = OFERTA_CONTRATO_NOVO.format(
        valor=reais(Decimal(oferta["valor"])),
        parcela=reais(Decimal(oferta["parcela"])),
        parcelas=oferta["parcelas"],
        taxa=reais(Decimal(oferta["taxa"])),
    )
    return {
        "c6_novo": {"situacao": "ofertado", **oferta},
        "status": "answered",
        "answer": resposta,
        "chave_mensagem": "textos:oferta_contrato_novo",
        "oferta_pendente": True,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=resposta)],
    }


def decline_c6(state: AgentState) -> dict[str, Any]:
    """Cliente recusou o contrato novo: a conversa segue para a portabilidade."""

    return {
        "c6_novo": {**(state.get("c6_novo") or {}), "situacao": "recusado"},
        "oferta_pendente": False,
        "resposta_oferta": None,
    }


def _dados_cliente(cliente: Any) -> calculo.DadosCliente | None:
    if not isinstance(cliente, dict):
        return None
    nascimento = parse_data(cliente.get("data_nascimento"))
    if nascimento is None:
        return None
    uf = cliente.get("uf")
    return calculo.DadosCliente(
        data_nascimento=nascimento,
        uf=str(uf).strip().upper() if uf else None,
    )


def calculate_portability(state: AgentState) -> dict[str, Any]:
    """Calcula a portabilidade INSS → C6 em código, sem LLM."""

    dados_hiscon = state.get("hiscon")
    if not dados_hiscon:
        return {
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    try:
        extrato = hiscon_mod.normalizar_extrato(dados_hiscon)
        dados_cliente = _dados_cliente(state.get("cliente"))
        resultado = calculo.calcular_portabilidade(
            extrato,
            dados_cliente,
            hoje_operacao(),
        )
    except Exception:
        return {
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    if not resultado.get("ok"):
        motivo = resultado.get("motivo") or "sem_resposta"
        atualizacao: dict[str, Any] = {
            "portability_result": resultado,
            "needs_human": True,
            "handoff_reason": motivo,
        }
        if motivo in MENSAGENS_FALHA_CALCULO:
            atualizacao["answer"] = MENSAGENS_FALHA_CALCULO[motivo]
            atualizacao["chave_mensagem"] = f"inss:{motivo}"
        return atualizacao

    elegiveis = [c for c in resultado.get("contratos", []) if c.get("elegivel")]
    if not elegiveis:
        return {
            "portability_result": resultado,
            "needs_human": True,
            "handoff_reason": "sem_portabilidade",
            "answer": mensagem.mensagem_sem_portabilidade(resultado),
            "chave_mensagem": "inss:sem_portabilidade",
        }

    return {"portability_result": resultado}


def present_offer(state: AgentState) -> dict[str, Any]:
    """Monta a mensagem fixa da oferta de portabilidade."""

    resultado = state.get("portability_result") or {}
    uf = (state.get("cliente") or {}).get("uf")
    resposta = mensagem.mensagem_oferta(resultado, uf)
    return {
        "status": "answered",
        "answer": resposta,
        "chave_mensagem": "inss:oferta",
        "oferta_pendente": True,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=resposta)],
    }
