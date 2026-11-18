"""Aba Membros (`/admin/membros`): a equipe, visível para todos (decisão 0023).

O servidor decide o que cada um recebe. Colega: quem é, o estado e a carga.
A própria pessoa e o gestor: também contato, acesso e atividade. Só o gestor:
situação, bloqueio, troca de senha pendente e a observação. As ações de gestão continuam em
`/admin/gestao/usuarios`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.modelos import Conversa, UsuarioPainel
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.painel import membros as regras
from saturday.painel.sessoes import agora as hora_atual
from saturday.privacidade import MASCARAS
from saturday.web.api.admin import url_foto
from saturday.web.dependencies import UsuarioLogado, get_fabrica, usuario_logado

router = APIRouter(prefix="/admin/membros", tags=["painel"])

Fabrica = Annotated[sessionmaker[Session], Depends(get_fabrica)]
Logado = Annotated[UsuarioLogado, Depends(usuario_logado)]


def _membro(
    usuario: UsuarioPainel, assumidas: int, quem: UsuarioLogado, agora: datetime
) -> dict[str, Any]:
    proprio = usuario.id == quem.id
    linha: dict[str, Any] = {
        "id": str(usuario.id),
        "nome": usuario.nome,
        "foto": url_foto(usuario.id, usuario.foto_chave),
        "cargo": usuario.cargo,
        "perfil": usuario.perfil,
        "estado": regras.estado(usuario, agora),
        "conversas_assumidas": assumidas,
        "voce": proprio,
        "nivel": "gestor" if quem.gestor else "proprio" if proprio else "colega",
    }
    if not (proprio or quem.gestor):
        return linha
    acesso = usuario.ultimo_acesso_em
    linha |= {
        "email": usuario.email,
        "telefone": MASCARAS["telefone"](usuario.telefone) if usuario.telefone else None,
        "pode_editar_agente": usuario.pode_editar_agente,
        "pode_testar_fluxos": usuario.pode_testar_fluxos,
        "ultimo_acesso_em": acesso.isoformat() if acesso else None,
        "criado_em": usuario.criado_em.isoformat(),
    }
    if not quem.gestor:
        return linha
    ate = usuario.bloqueado_ate
    if ate is not None and ate <= agora:
        ate = None
    linha |= {
        "situacao": "desativado" if not usuario.ativo else "bloqueado" if ate else "ativo",
        "bloqueado_ate": ate.isoformat() if ate else None,
        "tentativas_falhas": usuario.tentativas_falhas,
        "observacao": usuario.observacao,
        "trocar_senha": usuario.trocar_senha,
    }
    return linha


@router.get("")
def listar(quem: Logado, fabrica: Fabrica) -> list[dict[str, Any]]:
    """Ativos por nome; o gestor recebe também os desativados, no fim."""

    with abrir_sessao(fabrica) as sessao:
        consulta = select(UsuarioPainel).order_by(UsuarioPainel.ativo.desc(), UsuarioPainel.nome)
        if not quem.gestor:
            consulta = consulta.where(UsuarioPainel.ativo.is_(True))
        usuarios = sessao.scalars(consulta).all()
        assumidas = dict(
            sessao.execute(
                select(Conversa.atendente_id, func.count())
                .where(Conversa.atendimento == "assumida")
                .group_by(Conversa.atendente_id)
            ).all()
        )
        agora = hora_atual()
        return [_membro(u, int(assumidas.get(u.id, 0)), quem, agora) for u in usuarios]


@router.get("/{usuario_id}")
def detalhar(usuario_id: uuid.UUID, quem: Logado, fabrica: Fabrica) -> dict[str, Any]:
    with abrir_sessao(fabrica) as sessao:
        usuario = sessao.get(UsuarioPainel, usuario_id)
        # Desativado só existe para o gestor (decisão 0012: a linha fica).
        if usuario is None or not (usuario.ativo or quem.gestor):
            raise HTTPException(status_code=404, detail="membro não encontrado")
        agora = hora_atual()
        assumidas = sessao.scalar(
            select(func.count())
            .select_from(Conversa)
            .where(Conversa.atendimento == "assumida", Conversa.atendente_id == usuario.id)
        )
        linha = _membro(usuario, int(assumidas or 0), quem, agora)
        if linha["nivel"] != "colega":
            linha["atividade"] = regras.atividade(sessao, usuario.id, agora)
            linha["acoes"] = regras.ultimas_acoes(sessao, usuario.id)
        return linha
