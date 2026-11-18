"""Comandos de chat do membro testador (decisões 0020 e 0024).

Só leitura e textos: quem executa é o `AgentService`, depois de conferir que a
conversa é de membro. De cliente comum, o mesmo texto é mensagem qualquer.
"""

from __future__ import annotations

from typing import Any

from saturday.agent.clt import leitura
from saturday.agent.clt.mensagens import texto
from saturday.agent.clt.turno import PERGUNTAS, primeiro_nome
from saturday.agent.textos import COMANDO_REINICIAR
from saturday.privacidade import mascarar_cpf, mascarar_data, mascarar_email, mascarar_telefone

# Etapas do CLT aonde o `/ir` chega, na ordem da jornada.
DESTINOS = ("triagem", "empresa", "identificacao", "consentimento", "consultando", "oferta")
# Resultado que o simulador da Granatech dá à próxima consulta.
CENARIOS = (
    "sucesso",
    "sem_margem",
    "erro",
    "termo_pendente",
    # Consulta com sucesso, mas a pessoa vem sem o dado.
    "sem_nascimento",
    "sem_mae",
    "sem_endereco",
)

SEM_SIMULADOR = (
    "Este comando só funciona com a Granatech simulada. Aqui a consulta é real: "
    "a triagem, o SIM e a cota valem."
)
COM_HUMANO = "A conversa está com humano. Mande /devolver antes."
REINICIADA_COM_HUMANO = "A conversa continua com humano: mande /devolver."
JA_COM_HUMANO = "A conversa já está com humano."
JA_COM_IA = "A conversa já está com a IA."
ENVIADA_A_HUMANO = "Conversa enviada para atendimento humano (teste)."
DEVOLVIDA = "Conversa devolvida à IA. Continuo de onde parou."
DESCONHECIDO = "Comando desconhecido. Mande /ajuda."
LISTA_DE_DESTINOS = "Etapas: " + ", ".join(DESTINOS) + "."
LISTA_DE_CENARIOS = "Cenários: " + ", ".join(CENARIOS) + "."
CENARIO_ESCOLHIDO = "A próxima consulta vai dar: {cenario}."
# Turno de sistema do `/ir`: o nó CLT segue do pedido do SIM (`agent/clt/nos.py`).
EVENTO_IR = "membro:ir"

_MASCARAS = {
    "cpf": mascarar_cpf,
    "email": mascarar_email,
    "celular": mascarar_telefone,
    "nascimento": mascarar_data,
    "nome": primeiro_nome,
}


# Dados fictícios que cada etapa pulada deixa na jornada. O CPF é o do simulador.
_DADOS: dict[str, dict[str, Any]] = {
    "triagem": {"meses_casa": 36},
    "empresa": {"cnpj": "11222333000181"},
    "identificacao": {
        "cpf": "00189004967",
        "nome": "Membro de Teste",
        "nascimento": "1990-05-15",
        "sexo": "M",
    },
}
_CELULAR = "11999999999"
# Passo em que a jornada para em cada destino; no consentimento, o pedido do SIM.
_PASSO = {"triagem": "carteira", "empresa": "cnpj", "identificacao": "cpf", "consentimento": "sim"}


def jornada_em(destino: str, telefone: str | None, cenario: str | None) -> dict[str, Any]:
    """O `clt` do estado parado em ``destino``, como se o membro tivesse respondido.

    `consultando` e `oferta` param no pedido do SIM: quem abre a consulta é o
    grafo, com prova e cota. Com cenário, a consulta é nova; `oferta` pede
    sucesso e pula a escolha do vínculo.
    """

    alvo = destino if destino in _PASSO else "consentimento"
    dados: dict[str, Any] = {}
    for etapa in DESTINOS[: DESTINOS.index(alvo)]:
        dados.update(_DADOS[etapa])
    if alvo == "consentimento":
        dados.update(
            email="membro@exemplo.test", celular=leitura.celular(telefone or "") or _CELULAR
        )
    jornada: dict[str, Any] = {
        "etapa": alvo,
        "passo": _PASSO[alvo],
        "erros": 0,
        "dados": dados,
        "novas_simulacoes": 0,
    }
    if destino == "oferta":
        jornada.update(cenario="sucesso", pular_vinculo=True)
    elif destino == "consultando" or cenario:
        jornada["cenario"] = cenario or "sucesso"
    return jornada


def pergunta(jornada: dict[str, Any]) -> str:
    return str(texto(PERGUNTAS[jornada["passo"]]))


def ler(mensagem: str) -> tuple[str, str] | None:
    """`("/ir", "oferta")` para "/ir oferta"; `None` se não começa com barra."""

    partes = mensagem.strip().lower().split()
    if not partes or not partes[0].startswith("/"):
        return None
    return partes[0].replace("á", "a"), partes[1] if len(partes) > 1 else ""


def ajuda(simulador: bool) -> str:
    linhas = [
        "Comandos de teste:",
        "/estado: onde a jornada está",
        f"{COMANDO_REINICIAR}: zera a jornada",
        "/humano: manda para atendimento humano",
        "/devolver: volta para a IA",
    ]
    if simulador:
        linhas += [
            "/ir <etapa>: pula para " + ", ".join(DESTINOS),
            "/cenario <resultado>: " + ", ".join(CENARIOS),
        ]
    else:
        linhas.append("/ir e /cenario: só com a Granatech simulada")
    return "\n".join(linhas)


def estado(jornada: dict[str, Any], etapa: str | None, atendimento: str) -> str:
    """Resumo da jornada para o membro, com os dados pessoais mascarados."""

    dados = {
        chave: _MASCARAS[chave](str(valor)) if chave in _MASCARAS else valor
        for chave, valor in (jornada.get("dados") or {}).items()
    }
    return "\n".join(
        [
            f"Etapa: {etapa or 'início'}"
            + (f" ({jornada['passo']})" if jornada.get("passo") else ""),
            f"Atendimento: {atendimento}",
            f"Cenário da próxima consulta: {jornada.get('cenario') or 'sucesso'}",
            f"Consulta: {jornada.get('consulta') or 'nenhuma'}",
            "Dados: " + ("; ".join(f"{k} = {v}" for k, v in dados.items()) or "nenhum"),
        ]
    )
