"""Nós do grafo. Cada nó tem uma responsabilidade só."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage

from saturday.agent.state import AgentState
from saturday.config import (
    HISTORY_MAX_MESSAGES,
    HORARIO_EQUIPE,
    JEV_INTENT_THRESHOLD,
    TZ_EQUIPE,
    TZ_OPERACAO,
)
from saturday.portabilidade import calculo, mensagem
from saturday.portabilidade import hiscon as hiscon_mod
from saturday.portabilidade.regras import (
    IDADE_COLETA_MAX,
    IDADE_COLETA_MIN,
    IDADE_WEBPLUS,
    PRAZO_C6,
)
from saturday.services import anexos as anexos_service
from saturday.services import jev, llm

MENSAGENS_HANDOFF = {
    "pediu_humano": "Claro! Vou te transferir para um atendente da MEX.",
    "sem_resposta": (
        "Não consegui esclarecer isso por aqui. Vou te transferir para um atendente da MEX."
    ),
    "hiscon_nao_conferiu": (
        "Não consegui conferir os valores do seu extrato. Vou te transferir "
        "para um atendente da MEX."
    ),
    "extrato_ilegivel_repetido": (
        "Ainda não consegui ler o seu extrato. Vou te transferir para um atendente da MEX."
    ),
    "idade_fora_regra": (
        "No momento não atendemos essa faixa de idade. Vou te transferir para um atendente da MEX."
    ),
    "idade_prazo_96": (
        "Para a sua idade, o prazo disponível ainda não está nesta versão do "
        "atendimento. Vou te transferir para um atendente da MEX."
    ),
    "especie_nao_atendida": (
        "Esse tipo de benefício não é atendido por esta portabilidade. Vou te "
        "transferir para um atendente da MEX."
    ),
    "sem_portabilidade": (
        "No momento não encontrei um contrato com portabilidade para o C6. Vou "
        "te transferir para um atendente da MEX."
    ),
    "aceitou_portabilidade": (
        "Combinado! Um atendente da MEX vai seguir com a digitação da proposta."
    ),
    "dados_cliente_nao_informados": (
        "Não consegui confirmar os seus dados. Vou te transferir para um atendente da MEX."
    ),
}

MENSAGEM_FORA_HORARIO = (
    "O nosso atendimento humano funciona de segunda a sexta, das 8h às 17h. "
    "Um atendente responde no próximo dia útil, a partir das 8h."
)

MENSAGEM_RECUSA = "Tudo bem! Se mudar de ideia, é só me chamar. Obrigado pelo contato."

PERGUNTA_DATA = "Para continuar, me informe a sua data de nascimento (dd/mm/aaaa)."
PERGUNTA_DATA_INVALIDA = (
    "Não consegui entender a data. Me envie a data de nascimento no formato dd/mm/aaaa."
)
PERGUNTA_UF = "Como você tem 60 anos ou mais, preciso também da sua UF (estado). Qual é a sua UF?"
PERGUNTA_UF_INVALIDA = "Não consegui identificar a UF. Me envie a sigla do estado, por exemplo: MS."

MENSAGEM_EXTRATO_INCORRETO = (
    "O arquivo recebido não é o extrato de empréstimos do Meu INSS. No app ou "
    'site Meu INSS, escolha a opção "Extrato de Empréstimos" e envie o PDF ou '
    "uma foto."
)
MENSAGEM_EXTRATO_ILEGIVEL = (
    "Não consegui ler o extrato. Envie o extrato de empréstimos do Meu INSS em "
    "PDF ou uma foto nítida, com todas as páginas."
)
MENSAGEM_EXTRATO_MES_ERRADO = (
    "O extrato precisa ser do mês atual. Emita o extrato de empréstimos do Meu "
    "INSS hoje e envie novamente."
)

UFS_POR_NOME = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}
SIGLAS_UF = frozenset(UFS_POR_NOME.values())
PADRAO_DATA_NASCIMENTO = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def _hoje_operacao() -> date:
    return datetime.now(ZoneInfo(TZ_OPERACAO)).date()


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


def _normalizar_uf(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if not texto:
        return None
    sigla = texto.upper()
    if sigla in SIGLAS_UF:
        return sigla
    return UFS_POR_NOME.get(_sem_acento(texto))


def _data_nascimento(texto: str, hoje: date) -> tuple[str, int] | None:
    match = PADRAO_DATA_NASCIMENTO.fullmatch(texto.strip())
    if not match:
        return None
    dia, mes, ano_texto = match.groups()
    ano = int(ano_texto)
    if len(ano_texto) == 2:
        seculo = hoje.year - hoje.year % 100
        ano = seculo + ano
        if ano > hoje.year:
            ano -= 100
    try:
        nascimento = date(ano, int(mes), int(dia))
    except ValueError:
        return None

    idade = calculo.idade_em_anos(nascimento, hoje)
    if idade is None or idade < IDADE_COLETA_MIN or idade > IDADE_COLETA_MAX:
        return None
    return nascimento.isoformat(), idade


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


def _dentro_horario_equipe(agora: datetime | None = None) -> bool:
    tz = ZoneInfo(TZ_EQUIPE)
    agora = agora.astimezone(tz) if agora else datetime.now(tz)
    return (
        agora.weekday() in HORARIO_EQUIPE.dias
        and HORARIO_EQUIPE.inicio <= agora.hour < HORARIO_EQUIPE.fim
    )


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


def classify_intent(state: AgentState) -> dict[str, Any]:
    try:
        resultado = jev.classify(
            state.get("user_message", ""),
            bool(state.get("oferta_pendente")),
        )
    except Exception:
        # Erro do Jev não interrompe o atendimento: segue para o LLM.
        return {}

    intent = resultado.intent
    pediu_humano = intent == "humano" and resultado.intent_confidence >= JEV_INTENT_THRESHOLD
    if intent == "humano" and not pediu_humano:
        intent = "duvida"

    publico = resultado.publico
    if publico == "indefinido":
        publico = state.get("publico") or "indefinido"

    resposta_oferta = None
    if state.get("oferta_pendente"):
        resposta_oferta = resultado.resposta_oferta or "duvida"
        if (
            resposta_oferta not in {"aceita", "recusa"}
            or resultado.resposta_oferta_confidence < JEV_INTENT_THRESHOLD
        ):
            resposta_oferta = "duvida"

    atualizacao = {
        "intent": intent,
        "intent_confidence": resultado.intent_confidence,
        "publico": publico,
        "resposta_oferta": resposta_oferta,
    }
    if pediu_humano:
        atualizacao.update({"needs_human": True, "handoff_reason": "pediu_humano"})
    elif resposta_oferta == "aceita":
        atualizacao.update({"needs_human": True, "handoff_reason": "aceitou_portabilidade"})
    return atualizacao


def generate_answer(state: AgentState) -> dict[str, Any]:
    try:
        resposta = llm.responder(
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
        return {
            "status": "in_progress",
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    return {
        "status": "answered",
        "answer": resposta.resposta,
        "messages": [AIMessage(content=resposta.resposta)],
    }


def handoff(state: AgentState) -> dict[str, Any]:
    motivo = state.get("handoff_reason") or "sem_resposta"
    resposta = state.get("answer") or MENSAGENS_HANDOFF.get(
        motivo, MENSAGENS_HANDOFF["sem_resposta"]
    )
    if not _dentro_horario_equipe():
        resposta = f"{resposta} {MENSAGEM_FORA_HORARIO}"
    return {
        "status": "handoff",
        "needs_human": True,
        "handoff_reason": motivo,
        "answer": resposta,
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


def read_statement(state: AgentState) -> dict[str, Any]:
    try:
        anexos = anexos_service.carregar_anexos(state.get("attachments") or [])
    except anexos_service.AnexoInvalido:
        return _perguntar_extrato(state, anexos_service.mensagem_anexo_invalido())

    try:
        dados = llm.ler_extrato(anexos)
        extrato = hiscon_mod.normalizar_extrato(dados)
    except Exception:
        return _perguntar_extrato(state, MENSAGEM_EXTRATO_ILEGIVEL)

    status = hiscon_mod.validar_extrato(extrato, _hoje_operacao())
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
        "tentativas_extrato": 0,
        "portability_result": None,
        "oferta_pendente": False,
        "resposta_oferta": None,
    }


def check_customer_data(state: AgentState) -> dict[str, Any]:
    cliente: dict[str, Any] = dict(state.get("cliente") or {})
    hoje = _hoje_operacao()
    idade = calculo.idade_em_anos(cliente.get("data_nascimento"), hoje)

    if idade is None:
        return _pedido(PERGUNTA_DATA, "data_nascimento")

    uf = _normalizar_uf(cliente.get("uf"))
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
        dados = _data_nascimento(texto, _hoje_operacao())
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
        uf = _normalizar_uf(texto)
        if uf is None:
            return _falha_coleta(state, PERGUNTA_UF_INVALIDA)
        cliente["uf"] = uf
        return {
            "cliente": cliente,
            "tentativas_coleta": 0,
            "aguardando": None,
        }

    return {}


MENSAGENS_FALHA_CALCULO = {
    "idade_fora_regra": mensagem.MENSAGEM_IDADE_FORA,
    "idade_prazo_96": mensagem.MENSAGEM_IDADE_96,
    "especie_nao_atendida": mensagem.MENSAGEM_ESPECIE_NAO_ATENDIDA,
}


def calculate_portability(state: AgentState) -> dict[str, Any]:
    dados_hiscon = state.get("hiscon")
    if not dados_hiscon:
        return {
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    try:
        resultado = calculo.calcular_portabilidade(
            dados_hiscon,
            state.get("cliente") or {},
            _hoje_operacao(),
        )
    except Exception:
        return {
            "needs_human": True,
            "handoff_reason": "sem_resposta",
        }

    if not resultado.get("ok"):
        motivo = resultado.get("motivo") or "sem_resposta"
        atualizacao = {
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
