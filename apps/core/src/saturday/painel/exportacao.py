"""A conversa inteira em Markdown, para levar a outro lugar (inclusive a uma IA).

O painel mostra tudo isto ao vivo; o arquivo existe para conversar sobre a
jornada fora dele. A ficha sai mascarada, como na tela, e o texto das mensagens
sai literal, porque é sobre ele que se pergunta. O payload cru da Granatech fica
na aba Granatech: aqui entram só o status e os eventos, que é o que explica a
decisão.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from saturday.canais.whatsapp.janela import janela_aberta
from saturday.dados.modelos import (
    Consentimento,
    ConsultaGranatech,
    Conversa,
    Mensagem,
    PropostaGranatech,
    Turno,
)
from saturday.privacidade import MASCARAS
from saturday.settings import TZ_OPERACAO

FUSO = ZoneInfo(TZ_OPERACAO)

CANAL = {"whatsapp": "WhatsApp oficial", "evolution": "Evolution", "chat": "Chat"}
ATENDIMENTO = {"ia": "IA", "handoff": "Handoff", "assumida": "Assumida"}
AUTOR = {"cliente": "Cliente", "ia": "IA", "atendente": "Equipe", "sistema": "Sistema"}
ENTREGA = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "falhou"}
# Mesma ordem da ficha na tela; o nome fica de fora porque não é mascarado.
CAMPOS_DA_FICHA = {
    "cpf": "CPF",
    "telefone": "Telefone",
    "data_nascimento": "Nascimento",
    "email": "E-mail",
}


@dataclass(frozen=True)
class Retrato:
    """Tudo o que o arquivo mostra, já carregado e em ordem cronológica."""

    conversa: Conversa
    ficha: Mapping[str, Any]
    supervisao: Mapping[str, Any]
    mensagens: Sequence[Mensagem]
    consentimentos: Sequence[Consentimento]
    consultas: Sequence[ConsultaGranatech]
    propostas: Sequence[PropostaGranatech]
    turnos: Sequence[Turno]
    gestor: bool
    exportado_em: datetime
    exportado_por: str


def carregar(
    sessao: Session,
    conversa: Conversa,
    *,
    ficha: Mapping[str, Any],
    supervisao: Mapping[str, Any],
    gestor: bool,
    agora: datetime,
    exportado_por: str,
) -> Retrato:
    """Lê as tabelas que a conversa alcança: mensagens, provas, banco e turnos."""

    mensagens = sessao.scalars(
        select(Mensagem)
        .where(Mensagem.conversa_id == conversa.id)
        .order_by(Mensagem.criada_em, Mensagem.id)
    ).all()
    consentimentos = sessao.scalars(
        select(Consentimento)
        .where(Consentimento.conversa_id == conversa.id)
        .order_by(Consentimento.criada_em, Consentimento.id)
    ).all()
    consultas = sessao.scalars(
        select(ConsultaGranatech)
        .where(ConsultaGranatech.conversa_id == conversa.id)
        .order_by(ConsultaGranatech.criada_em, ConsultaGranatech.id)
    ).all()
    # A proposta não guarda a conversa: ela chega pela consulta que a originou.
    propostas = sessao.scalars(
        select(PropostaGranatech)
        .join(ConsultaGranatech, ConsultaGranatech.id == PropostaGranatech.consulta_id)
        .where(ConsultaGranatech.conversa_id == conversa.id)
        .order_by(PropostaGranatech.intencao_em, PropostaGranatech.id)
    ).all()
    turnos = sessao.scalars(
        select(Turno).where(Turno.conversa_id == conversa.id).order_by(Turno.criado_em, Turno.id)
    ).all()
    return Retrato(
        conversa=conversa,
        ficha=ficha,
        supervisao=supervisao,
        mensagens=mensagens,
        consentimentos=consentimentos,
        consultas=consultas,
        propostas=propostas,
        turnos=turnos,
        gestor=gestor,
        exportado_em=agora,
        exportado_por=exportado_por,
    )


def conversa_em_markdown(retrato: Retrato) -> str:
    """O arquivo inteiro: cabeçalho, ficha, jornada com o banco e as mensagens."""

    partes = [
        _cabecalho(retrato),
        _secao_ficha(retrato.ficha),
        _secao_consentimentos(retrato.consentimentos),
        _secao_granatech(retrato.consultas, retrato.propostas),
        _secao_trilha(retrato.turnos, gestor=retrato.gestor),
        _secao_mensagens(retrato.mensagens),
    ]
    return "\n\n".join(parte for parte in partes if parte) + "\n"


# ------------------------------------------------------------------ formatação


def _quando(valor: object) -> str:
    """Data na hora da operação, em ordem legível e ordenável."""

    momento: object = valor
    if isinstance(valor, str):
        try:
            momento = datetime.fromisoformat(valor)
        except ValueError:
            return valor
    if isinstance(momento, datetime):
        return momento.astimezone(FUSO).strftime("%Y-%m-%d %H:%M")
    return ""


def _reais(valor: Decimal) -> str:
    return "R$ " + f"{valor:,.2f}".translate(str.maketrans(",.", ".,"))


def _dolar(valor: float) -> str:
    """Igual à aba IA: um turno custa frações de centavo, então quatro casas."""

    if 0 < valor < 0.0001:
        return "< US$ 0,0001"
    casas = 4 if valor != 0 and abs(valor) < 1 else 2
    return "US$ " + f"{valor:,.{casas}f}".translate(str.maketrans(",.", ".,"))


def _texto(valor: object) -> str:
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False)


def _campo(rotulo: str, valor: object) -> str:
    """Campo sem valor não vira linha: ausência já diz o que falta."""

    if valor is None or valor == "":
        return ""
    return f"- **{rotulo}:** {valor}"


def _lista(campos: Sequence[str]) -> str:
    return "\n".join(campo for campo in campos if campo)


def _cabecalho(retrato: Retrato) -> str:
    conversa = retrato.conversa
    titulo = f"# Conversa — {CANAL.get(conversa.canal, conversa.canal)}"
    if conversa.telefone:
        titulo += f" · {MASCARAS['telefone'](conversa.telefone)}"
    linhas = [
        _campo("Atendimento", ATENDIMENTO.get(conversa.atendimento, conversa.atendimento)),
        _campo("Etapa", conversa.etapa),
        _campo("Conversa", f"`{conversa.id}`"),
        _campo("Aberta em", _quando(conversa.criada_em)),
        _campo("Cliente escreveu pela última vez em", _quando(conversa.ultima_entrada_em)),
    ]
    if conversa.canal == "whatsapp":
        aberta = janela_aberta(conversa.ultima_entrada_em, retrato.exportado_em)
        linhas.append(_campo("Janela de 24 h", "aberta" if aberta else "fechada"))
    atencao = retrato.supervisao.get("atencao") or []
    linhas += [
        _campo("Mensagens", len(retrato.mensagens)),
        _campo("Alertas", ", ".join(str(motivo) for motivo in atencao)),
        _campo("Motivo do handoff", retrato.supervisao.get("motivo_handoff")),
        _campo("Exportado em", f"{_quando(retrato.exportado_em)} por {retrato.exportado_por}"),
    ]
    nota = "_A ficha sai mascarada, como na tela; o texto das mensagens é o original._"
    return "\n".join([titulo, "", _lista(linhas), "", nota])


def _secao_ficha(ficha: Mapping[str, Any]) -> str:
    dados = ficha.get("dados") or {}
    linhas = [_campo("Nome", ficha.get("nome"))]
    linhas += [
        _campo(rotulo, dados[campo])
        for campo, rotulo in CAMPOS_DA_FICHA.items()
        if dados.get(campo)
    ]
    linhas += [
        _campo("UF", ficha.get("uf")),
        _campo("Público", ficha.get("publico")),
        _campo("Saída para a equipe", ficha.get("handoff_reason")),
    ]
    return "\n".join(["## Ficha do cliente", "", _lista(linhas)])


def _secao_consentimentos(consentimentos: Sequence[Consentimento]) -> str:
    if not consentimentos:
        return ""
    blocos = ["## Consentimentos"]
    for consentimento in consentimentos:
        texto = consentimento.texto_mostrado.strip()
        blocos.append(
            "\n".join(
                [
                    f"### {_quando(consentimento.criada_em)} · {consentimento.tipo}",
                    "",
                    "Texto mostrado:",
                    "",
                    *[f"> {linha}" for linha in (texto.splitlines() or [""])],
                    "",
                    _lista(
                        [
                            _campo("Resposta literal", f'"{consentimento.resposta_literal}"'),
                            _campo("Versão", consentimento.versao),
                            _campo("wamid", consentimento.wamid),
                            _campo(
                                "CPF",
                                MASCARAS["cpf"](consentimento.cpf) if consentimento.cpf else None,
                            ),
                        ]
                    ),
                ]
            )
        )
    return "\n\n".join(blocos)


def _secao_granatech(
    consultas: Sequence[ConsultaGranatech], propostas: Sequence[PropostaGranatech]
) -> str:
    if not consultas and not propostas:
        return ""
    blocos = [
        "## Granatech",
        *[_consulta(linha) for linha in consultas],
        *[_proposta(linha) for linha in propostas],
    ]
    return "\n\n".join(blocos)


def _consulta(linha: ConsultaGranatech) -> str:
    linhas = [
        _campo("CPF", MASCARAS["cpf"](linha.cpf)),
        _campo("Criada em", _quando(linha.criada_em)),
        _campo("Atualizada em", _quando(linha.atualizada_em)),
        _campo("Link do termo", linha.link_termo),
    ]
    if linha.historico:
        linhas.append("- **Eventos recebidos:**")
        for evento in linha.historico:
            quando = _quando(evento.get("recebido_em"))
            status = str(evento.get("status") or "?")
            linhas.append(f"  - {status}{f' · {quando}' if quando else ''}")
    return "\n".join([f"### Consulta {linha.id_externo} · {linha.status}", "", _lista(linhas)])


def _proposta(linha: PropostaGranatech) -> str:
    linhas = [
        _campo("Consulta", linha.consulta_id),
        _campo("Status", linha.status),
        _campo("Notificação", linha.tipo_notificacao),
        _campo("Envio", linha.estado_envio),
        _campo("Parcela", f"{linha.numero_parcelas} × {_reais(linha.valor_parcela)}"),
        _campo("Intenção em", _quando(linha.intencao_em)),
        _campo("Atualizada em", _quando(linha.atualizada_em)),
    ]
    if linha.historico:
        linhas.append("- **Eventos recebidos:**")
        for evento in linha.historico:
            passos = [str(evento.get("status") or "?"), _quando(evento.get("recebido_em"))]
            if evento.get("tipo_notificacao"):
                passos.insert(1, str(evento["tipo_notificacao"]))
            texto = " · ".join(passos)
            if evento.get("informacoes"):
                texto += f" — {_texto(evento['informacoes'])}"
            linhas.append(f"  - {texto}")
    nome = linha.id_externo or f"interna {linha.id}"
    return "\n".join(
        [f"### Proposta {nome} · {linha.status or linha.estado_envio}", "", _lista(linhas)]
    )


def _secao_trilha(turnos: Sequence[Turno], *, gestor: bool) -> str:
    if not turnos:
        return ""
    blocos = ["## Trilha da IA"]
    if gestor:
        tokens = f"{sum(turno.tokens for turno in turnos):,}".replace(",", ".")
        blocos.append(
            "\n".join(
                [
                    f"- **Turnos:** {len(turnos)}",
                    f"- **Custo:** {_dolar(sum(turno.custo_usd for turno in turnos))}",
                    f"- **Tokens:** {tokens}",
                ]
            )
        )
    for turno in turnos:
        linhas = [
            _campo("Caminho", " → ".join(turno.caminho)),
            _campo("Status", turno.status),
        ]
        classificacao = turno.classificacao or {}
        if classificacao:
            linhas += [
                _campo("Intenção", classificacao.get("intencao")),
                _campo("Público", classificacao.get("publico")),
            ]
            confianca = classificacao.get("confianca")
            if confianca is not None:
                linhas.append(_campo("Confiança", f"{round(float(confianca) * 100)}%"))
        if turno.motivo:
            linhas.append(_campo("Motivo", turno.motivo))
        if turno.chamadas:
            linhas.append("- **Chamadas:**")
            linhas += [f"  - {_chamada(chamada, gestor)}" for chamada in turno.chamadas]
        titulo = f"### {_quando(turno.criado_em)}"
        if turno.etapa:
            titulo += f" · {turno.etapa}"
        blocos.append("\n".join([titulo, "", _lista(linhas)]))
    return "\n\n".join(blocos)


def _chamada(chamada: Mapping[str, Any], gestor: bool) -> str:
    partes = [str(chamada.get("nome") or "?"), str(chamada.get("status") or "—")]
    latencia = chamada.get("latencia_ms")
    if latencia is not None:
        partes.append(f"{round(float(latencia))} ms")
    if gestor:
        custo = chamada.get("custo_usd")
        if custo is not None:
            partes.append(_dolar(float(custo)))
        entrada = chamada.get("tokens_entrada")
        if entrada is not None:
            partes.append(f"{entrada}+{chamada.get('tokens_saida') or 0} tok")
    return " · ".join(partes)


def _secao_mensagens(mensagens: Sequence[Mensagem]) -> str:
    blocos = ["## Mensagens"]
    if not mensagens:
        blocos.append("_Nenhuma mensagem registrada._")
    for mensagem in mensagens:
        cabecalho = f"**{_quando(mensagem.criada_em)} · {AUTOR.get(mensagem.autor, mensagem.autor)}"
        if mensagem.status_entrega:
            entrega = ENTREGA.get(mensagem.status_entrega, mensagem.status_entrega)
            cabecalho += f" · {entrega}"
        cabecalho += "**"
        anexos = [
            f"_[anexo: {anexo.get('mime_type') or 'arquivo'}]_" for anexo in mensagem.anexos or []
        ]
        corpo = mensagem.conteudo.strip() or "_sem texto_"
        blocos.append("\n".join([cabecalho, "", corpo, *anexos]))
    return "\n\n".join(blocos)
