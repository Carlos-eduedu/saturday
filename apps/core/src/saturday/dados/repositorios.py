"""Consultas e gravações das tabelas usadas nesta fase."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import Alerta, Conversa, Mensagem, UsuarioPainel

# Canal do `LISTEN` da API (`web/eventos.py`). O aviso leva só tipo e IDs:
# nada de dado pessoal passa por ele.
CANAL_PAINEL = "painel"


def notificar(sessao: Session, tipo: str, **ids: Any) -> None:
    """Avisa o painel. O Postgres só entrega no commit: rollback não avisa."""

    carga = json.dumps({"tipo": tipo, **{k: str(v) for k, v in ids.items()}})
    sessao.execute(select(func.pg_notify(CANAL_PAINEL, carga)))


def obter_ou_criar_conversa(
    sessao: Session,
    conversation_id: str,
    *,
    canal: str = "chat",
    telefone: str | None = None,
    phone_number_id: str | None = None,
) -> Conversa:
    conversa = sessao.scalar(select(Conversa).where(Conversa.conversation_id == conversation_id))
    if conversa is None:
        conversa = Conversa(
            conversation_id=conversation_id,
            canal=canal,
            telefone=telefone,
            phone_number_id=phone_number_id,
        )
        sessao.add(conversa)
        sessao.flush()
        return conversa

    # O cliente fica preso ao número em que escreveu; o telefone só é gravado
    # uma vez, para não reescrever a cada turno.
    if telefone and conversa.telefone != telefone:
        conversa.telefone = telefone
    if phone_number_id:
        conversa.phone_number_id = phone_number_id
    return conversa


def marcar_entrada(conversa: Conversa) -> None:
    """Toda mensagem do cliente reabre a janela de 24 h do canal."""

    conversa.ultima_entrada_em = func.now()


def registrar_entrada(
    sessao: Session,
    conversa: Conversa,
    *,
    message_id: str | None,
    conteudo: str,
    anexos: list[dict[str, Any]] | None = None,
) -> bool:
    """Grava a mensagem do cliente. ``False`` quando o ``message_id`` já existe.

    A decisão é do banco, não de uma lista em memória: ``ON CONFLICT DO NOTHING``
    sobre a chave única é o que vale com dois workers ao mesmo tempo.
    """

    marcar_entrada(conversa)
    if message_id is None:
        sessao.add(
            Mensagem(
                conversa_id=conversa.id,
                direcao="entrada",
                autor="cliente",
                conteudo=conteudo,
                anexos=anexos,
            )
        )
        sessao.flush()
        notificar(sessao, "mensagem", conversa=conversa.id)
        return True

    resultado = sessao.execute(
        insert(Mensagem)
        .values(
            conversa_id=conversa.id,
            direcao="entrada",
            autor="cliente",
            message_id=message_id,
            conteudo=conteudo,
            anexos=anexos,
        )
        .on_conflict_do_nothing(index_elements=["conversa_id", "direcao", "message_id"])
        .returning(Mensagem.id)
    )
    inserida = resultado.scalar_one_or_none() is not None
    if inserida:
        notificar(sessao, "mensagem", conversa=conversa.id)
    return inserida


def registrar_saida(
    sessao: Session,
    conversa: Conversa,
    *,
    conteudo: str,
    message_id: str | None = None,
    autor: str = "ia",
    usuario_id: uuid.UUID | None = None,
    anexos: list[dict[str, Any]] | None = None,
    turno_id: int | None = None,
    chave_mensagem: str | None = None,
) -> int:
    """Grava a resposta e devolve o id.

    O id volta para o outbox: quando a Meta confirmar o envio, é nesta linha que
    o `wamid` e o status de entrega vão ser gravados.
    """

    linha = Mensagem(
        conversa_id=conversa.id,
        direcao="saida",
        autor=autor,
        usuario_id=usuario_id,
        message_id=message_id,
        conteudo=conteudo,
        anexos=anexos,
        turno_id=turno_id,
        chave_mensagem=chave_mensagem,
    )
    sessao.add(linha)
    sessao.flush()
    notificar(sessao, "mensagem", conversa=conversa.id)
    return linha.id


def buscar_conversa(sessao: Session, conversation_id: str) -> Conversa | None:
    return sessao.scalar(select(Conversa).where(Conversa.conversation_id == conversation_id))


def marcar_envio(
    sessao: Session,
    mensagem_id: int,
    *,
    wamid: str | None,
    status: str,
) -> None:
    """Guarda a identificação da Meta na mensagem que a originou."""

    linha = sessao.get(Mensagem, mensagem_id)
    if linha is None:
        return
    if wamid:
        linha.wamid = wamid
    linha.status_entrega = status
    sessao.flush()


def atualizar_status(sessao: Session, *, wamid: str, status: str) -> bool:
    """Aplica um `statuses` do webhook. ``False`` se a mensagem é desconhecida."""

    linha = sessao.scalar(select(Mensagem).where(Mensagem.wamid == wamid))
    if linha is None:
        return False
    linha.status_entrega = status
    sessao.flush()
    notificar(sessao, "mensagem", conversa=linha.conversa_id)
    return True


def mudar_atendimento(
    sessao: Session,
    conversa: Conversa,
    atendimento: str,
    *,
    atendente_id: uuid.UUID | None = None,
) -> None:
    """Muda quem responde a conversa: `ia`, `handoff` ou `assumida`."""

    conversa.atendimento = atendimento
    conversa.atendente_id = atendente_id if atendimento == "assumida" else None
    conversa.atendimento_em = func.now()
    sessao.flush()
    notificar(sessao, "conversa", conversa=conversa.id)


def abrir_alerta(
    sessao: Session,
    tipo: str,
    *,
    conversa_id: uuid.UUID | None = None,
    detalhe: dict[str, Any] | None = None,
    unico: bool = False,
) -> Alerta:
    """Abre um alerta; com `unico`, reaproveita o aberto do mesmo tipo na conversa."""

    if unico:
        aberto = sessao.scalars(
            select(Alerta).where(
                Alerta.tipo == tipo,
                Alerta.conversa_id == conversa_id,
                Alerta.resolvido_em.is_(None),
            )
        ).first()
        if aberto is not None:
            return aberto
    alerta = Alerta(tipo=tipo, conversa_id=conversa_id, detalhe=detalhe)
    sessao.add(alerta)
    sessao.flush()
    notificar(sessao, "alerta", alerta=alerta.id)
    return alerta


def resolver_alertas(
    sessao: Session,
    conversa_id: uuid.UUID,
    tipos: tuple[str, ...],
    usuario_id: uuid.UUID,
) -> list[int]:
    """Resolve os alertas abertos desses tipos na conversa, em nome de quem agiu."""

    ids = list(
        sessao.scalars(
            update(Alerta)
            .where(
                Alerta.conversa_id == conversa_id,
                Alerta.tipo.in_(tipos),
                Alerta.resolvido_em.is_(None),
            )
            .values(resolvido_por=usuario_id, resolvido_em=func.now())
            .returning(Alerta.id)
        )
    )
    for alerta_id in ids:
        notificar(sessao, "alerta", alerta=alerta_id)
    return ids


def reabrir_alertas(sessao: Session, ids: list[int]) -> list[int]:
    """Volta a abrir alertas resolvidos (o desfazer da ação que os resolveu)."""

    if not ids:
        return []
    reabertos = list(
        sessao.scalars(
            update(Alerta)
            .where(Alerta.id.in_(ids), Alerta.resolvido_em.is_not(None))
            .values(resolvido_por=None, resolvido_em=None)
            .returning(Alerta.id)
        )
    )
    for alerta_id in reabertos:
        notificar(sessao, "alerta", alerta=alerta_id)
    return reabertos


# ------------------------------------------------------------------ membros testadores


def testadores(sessao: Session) -> dict[str, str]:
    """Telefone → nome de quem testa fluxos pelo WhatsApp (decisão 0020).

    Membro ativo, com a permissão "testar fluxos" e telefone no perfil. Os dois
    telefones estão no mesmo formato (DDD + número), o da conversa e o do perfil.
    """

    linhas = sessao.execute(
        select(UsuarioPainel.telefone, UsuarioPainel.nome).where(
            UsuarioPainel.ativo.is_(True),
            UsuarioPainel.pode_testar_fluxos.is_(True),
            UsuarioPainel.telefone.is_not(None),
        )
    ).all()
    return {telefone: nome for telefone, nome in linhas if telefone}


def testador(sessao: Session, telefone: str | None) -> str | None:
    """Nome do membro testador dono deste telefone, ou None."""

    return testadores(sessao).get(telefone) if telefone else None
