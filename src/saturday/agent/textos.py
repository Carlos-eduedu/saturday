"""Textos fixos do atendimento.

Nenhum texto com valores é gerado por LLM. Os números vêm exclusivamente do
resultado da portabilidade e são formatados em ``portabilidade.mensagem``.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from saturday.portabilidade import mensagem
from saturday.settings import HORARIO_EQUIPE, TZ_EQUIPE

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
    "erro_interno": (
        "Tive um problema para continuar o seu atendimento. Vou te transferir "
        "para um atendente da MEX."
    ),
}

MENSAGEM_FORA_HORARIO = (
    "O nosso atendimento humano funciona de segunda a sexta, das 8h às 17h. "
    "Um atendente responde no próximo dia útil, a partir das 8h."
)

MENSAGEM_RECUSA = "Tudo bem! Se mudar de ideia, é só me chamar. Obrigado pelo contato."

MENSAGEM_SEM_TEXTO = "Não consegui ver a sua mensagem. Pode escrever o que você precisa?"

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

MENSAGENS_FALHA_CALCULO = {
    "idade_fora_regra": mensagem.MENSAGEM_IDADE_FORA,
    "idade_prazo_96": mensagem.MENSAGEM_IDADE_96,
    "especie_nao_atendida": mensagem.MENSAGEM_ESPECIE_NAO_ATENDIDA,
}


def dentro_horario_equipe(agora: datetime | None = None) -> bool:
    tz = ZoneInfo(TZ_EQUIPE)
    agora = agora.astimezone(tz) if agora else datetime.now(tz)
    return (
        agora.weekday() in HORARIO_EQUIPE.dias
        and HORARIO_EQUIPE.inicio <= agora.hour < HORARIO_EQUIPE.fim
    )


def mensagem_handoff(motivo: str, resposta: str | None = None) -> str:
    texto = resposta or MENSAGENS_HANDOFF.get(motivo, MENSAGENS_HANDOFF["sem_resposta"])
    if not dentro_horario_equipe():
        texto = f"{texto} {MENSAGEM_FORA_HORARIO}"
    return texto
