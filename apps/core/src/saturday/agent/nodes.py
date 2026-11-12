"""Nós do grafo. Cada nó tem uma responsabilidade só."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from saturday.agent.coleta import hoje_operacao, normalizar_uf, parse_data_nascimento
from saturday.agent.context import AgentContext
from saturday.agent.state import AgentState
from saturday.agent.textos import (
    MENSAGEM_BOAS_VINDAS,
    MENSAGEM_EXTRATO_ILEGIVEL,
    MENSAGEM_EXTRATO_INCORRETO,
    MENSAGEM_EXTRATO_MES_ERRADO,
    MENSAGEM_NAO_ENTENDI,
    MENSAGEM_RECUSA,
    MENSAGEM_SEM_TEXTO,
    MENSAGENS_FALHA_CALCULO,
    PERGUNTA_DATA,
    PERGUNTA_DATA_INVALIDA,
    PERGUNTA_UF,
    PERGUNTA_UF_INVALIDA,
    mensagem_handoff,
)
from saturday.portabilidade import calculo, mensagem
from saturday.portabilidade import hiscon as hiscon_mod
from saturday.portabilidade.regras import IDADE_WEBPLUS, PRAZO_C6
from saturday.portabilidade.util import parse_data
from saturday.services.anexos import AnexoInvalido
from saturday.settings import HISTORY_MAX_MESSAGES, TZ_OPERACAO


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


def _ultima_mensagem_agente(state: AgentState) -> str | None:
    for mensagem_atual in reversed(state.get("messages") or []):
        if not isinstance(mensagem_atual, AIMessage):
            continue
        conteudo = mensagem_atual.content
        return conteudo if isinstance(conteudo, str) else str(conteudo)
    return None


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


def _pedido(pergunta: str, aguardando: str) -> dict[str, Any]:
    return {
        "status": "answered",
        "answer": pergunta,
        "aguardando": aguardando,
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
    return {
        "status": "answered",
        "answer": MENSAGEM_SEM_TEXTO,
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
    try:
        resultado = runtime.context.jev.classify(
            state.get("user_message", ""),
            bool(state.get("oferta_pendente")),
            oferta=_ultima_mensagem_agente(state),
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
    if publico == "indefinido":
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
        atualizacao.update({"needs_human": True, "handoff_reason": "aceitou_portabilidade"})
    return atualizacao


def generate_answer(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    try:
        resposta = runtime.context.llm.responder(
            _historico(state),
            _resumo_portabilidade(state),
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
        "tentativas_resposta": 0,
        "messages": [AIMessage(content=resposta.resposta)],
    }


def boas_vindas(state: AgentState) -> dict[str, Any]:
    return {
        "status": "answered",
        "answer": MENSAGEM_BOAS_VINDAS,
        "needs_human": False,
        "tentativas_resposta": 0,
        "messages": [AIMessage(content=MENSAGEM_BOAS_VINDAS)],
    }


def handoff(state: AgentState) -> dict[str, Any]:
    motivo = state.get("handoff_reason") or "sem_resposta"
    resposta = mensagem_handoff(motivo, state.get("answer"))
    return {
        "status": "handoff",
        "needs_human": True,
        "handoff_reason": motivo,
        "answer": resposta,
        "handoff_em": datetime.now(ZoneInfo(TZ_OPERACAO)).isoformat(),
        "messages": [AIMessage(content=resposta)],
    }


def decline_offer(state: AgentState) -> dict[str, Any]:
    return {
        "status": "answered",
        "answer": MENSAGEM_RECUSA,
        "oferta_pendente": False,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=MENSAGEM_RECUSA)],
    }


def _perguntar_extrato(state: AgentState, pergunta: str) -> dict[str, Any]:
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
        "needs_human": False,
        "messages": [AIMessage(content=pergunta)],
    }


def read_statement(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    try:
        anexos = runtime.context.anexos.carregar_anexos(state.get("attachments") or [])
    except AnexoInvalido:
        return _perguntar_extrato(state, runtime.context.anexos.mensagem_anexo_invalido())

    try:
        dados = runtime.context.llm.ler_extrato(anexos)
        extrato = hiscon_mod.normalizar_extrato(dados)
    except Exception:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_ILEGIVEL)

    status = hiscon_mod.validar_extrato(extrato, hoje_operacao())
    if status == hiscon_mod.STATUS_NAO_HISCON:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_INCORRETO)
    if status == hiscon_mod.STATUS_ILEGIVEL:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_ILEGIVEL)
    if status == hiscon_mod.STATUS_MES_ERRADO:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_MES_ERRADO)

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
            "needs_human": True,
            "handoff_reason": "especie_nao_atendida",
        }

    return {
        "hiscon": dados_extrato,
        "hiscon_recebido_em": datetime.now(ZoneInfo(TZ_OPERACAO)).isoformat(),
        "tentativas_extrato": 0,
        "portability_result": None,
        "oferta_pendente": False,
        "resposta_oferta": None,
    }


def check_customer_data(state: AgentState) -> dict[str, Any]:
    cliente: dict[str, Any] = dict(state.get("cliente") or {})
    hoje = hoje_operacao()
    idade = calculo.idade_em_anos(cliente.get("data_nascimento"), hoje)

    if idade is None:
        return _pedido(PERGUNTA_DATA, "data_nascimento")

    uf = normalizar_uf(cliente.get("uf"))
    if uf is not None:
        cliente["uf"] = uf

    if idade >= IDADE_WEBPLUS and uf is None:
        return _pedido(PERGUNTA_UF, "uf")

    return {
        "status": "in_progress",
        "cliente": cliente,
        "aguardando": None,
        "tentativas_coleta": 0,
    }


def _falha_coleta(state: AgentState, pergunta: str) -> dict[str, Any]:
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
        "needs_human": False,
        "messages": [AIMessage(content=pergunta)],
    }


def collect_customer_data(state: AgentState) -> dict[str, Any]:
    aguardando = state.get("aguardando")
    cliente: dict[str, Any] = dict(state.get("cliente") or {})
    texto = state.get("user_message", "")

    if aguardando == "data_nascimento":
        dados = parse_data_nascimento(texto, hoje_operacao())
        if dados is None:
            return _falha_coleta(state, PERGUNTA_DATA_INVALIDA)
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
            return _falha_coleta(state, PERGUNTA_UF_INVALIDA)
        cliente["uf"] = uf
        return {
            "cliente": cliente,
            "tentativas_coleta": 0,
            "aguardando": None,
        }

    return {}


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
        return atualizacao

    elegiveis = [c for c in resultado.get("contratos", []) if c.get("elegivel")]
    if not elegiveis:
        return {
            "portability_result": resultado,
            "needs_human": True,
            "handoff_reason": "sem_portabilidade",
            "answer": mensagem.mensagem_sem_portabilidade(resultado),
        }

    return {"portability_result": resultado}


def present_offer(state: AgentState) -> dict[str, Any]:
    resultado = state.get("portability_result") or {}
    uf = (state.get("cliente") or {}).get("uf")
    resposta = mensagem.mensagem_oferta(resultado, uf)
    return {
        "status": "answered",
        "answer": resposta,
        "oferta_pendente": True,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=resposta)],
    }
