"""Gestão de usuários do painel pela aba Usuários (decisão 0012).

Só gestor chega aqui, menos em `trocar_propria_senha`, que é de cada pessoa
(decisão 0030). Excluir é desativar: a linha fica para a auditoria e as
mensagens continuarem dizendo quem fez o quê. Cada função roda dentro da
transação de quem chama e grava `auditoria` nela; a senha nunca entra no
detalhe.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from saturday.dados import atendimento
from saturday.dados.modelos import Conversa, UsuarioPainel
from saturday.dados.trava import travar_e_reler
from saturday.painel.acoes import AcaoRecusada
from saturday.painel.auditoria import auditar
from saturday.painel.sessoes import (
    PERFIS,
    TAMANHO_MINIMO_SENHA,
    conferir_senha,
    criar_usuario,
    encerrar_outras_sessoes,
    encerrar_sessoes,
    gerar_hash,
    normalizar_email,
)

TAMANHO_MAXIMO_NOME = 80
TAMANHO_MAXIMO_CARGO = 60
TAMANHO_MAXIMO_OBSERVACAO = 500


def _validar_nome(nome: str) -> str:
    limpo = " ".join(nome.split())
    if not limpo or len(limpo) > TAMANHO_MAXIMO_NOME:
        raise AcaoRecusada(422, f"nome: de 1 a {TAMANHO_MAXIMO_NOME} caracteres")
    return limpo


def _texto_opcional(valor: str, maximo: int, campo: str) -> str | None:
    """Texto livre do gestor: espaços aparados, vazio vira ausência."""

    valor = " ".join(valor.split())
    if len(valor) > maximo:
        raise AcaoRecusada(422, f"{campo} longa demais (até {maximo} caracteres)")
    return valor or None


def _validar_senha(senha: str) -> None:
    if len(senha) < TAMANHO_MINIMO_SENHA:
        raise AcaoRecusada(422, f"a senha precisa de pelo menos {TAMANHO_MINIMO_SENHA} caracteres")


def _validar_perfil(perfil: str) -> None:
    if perfil not in PERFIS:
        raise AcaoRecusada(422, "perfil: atendente ou gestor")


def _validar_email(email: str) -> str:
    limpo = normalizar_email(email)
    local, arroba, dominio = limpo.partition("@")
    if not local or not arroba or "." not in dominio or len(limpo) > 254:
        raise AcaoRecusada(422, "e-mail inválido")
    return limpo


def _buscar(sessao: Session, usuario_id: uuid.UUID) -> UsuarioPainel:
    usuario = sessao.scalar(
        select(UsuarioPainel).where(UsuarioPainel.id == usuario_id).with_for_update()
    )
    if usuario is None:
        raise AcaoRecusada(404, "usuário não encontrado")
    return usuario


def _email_em_uso(sessao: Session, email: str, exceto: uuid.UUID | None = None) -> None:
    dono = sessao.scalar(select(UsuarioPainel).where(UsuarioPainel.email == email))
    if dono is None or dono.id == exceto:
        return
    if not dono.ativo:
        raise AcaoRecusada(409, "já existe um usuário desativado com esse e-mail: reative-o")
    raise AcaoRecusada(409, "já existe um usuário com esse e-mail")


def _exigir_outro_gestor(sessao: Session, alvo: UsuarioPainel) -> None:
    """Recusa a mudança que deixaria o painel sem gestor ativo.

    Trava as linhas dos gestores ativos: dois gestores rebaixando um ao outro
    ao mesmo tempo não passam os dois.
    """

    gestores = sessao.scalars(
        select(UsuarioPainel.id)
        .where(UsuarioPainel.perfil == "gestor", UsuarioPainel.ativo.is_(True))
        .with_for_update()
    ).all()
    if set(gestores) <= {alvo.id}:
        raise AcaoRecusada(409, "o painel precisa de pelo menos um gestor ativo")


def conversas_assumidas(sessao: Session, usuario_id: uuid.UUID) -> int:
    total = sessao.scalar(
        select(func.count())
        .select_from(Conversa)
        .where(Conversa.atendimento == "assumida", Conversa.atendente_id == usuario_id)
    )
    return int(total or 0)


def criar(
    sessao: Session, autor_id: uuid.UUID, nome: str, email: str, perfil: str, senha: str
) -> UsuarioPainel:
    nome = _validar_nome(nome)
    email = _validar_email(email)
    _validar_perfil(perfil)
    _validar_senha(senha)
    _email_em_uso(sessao, email)
    try:
        with sessao.begin_nested():
            # A senha inicial é do gestor: a pessoa troca no primeiro acesso.
            usuario = criar_usuario(sessao, email, senha, perfil, nome, trocar_senha=True)
    except IntegrityError as exc:
        # Outro gestor cadastrou o mesmo e-mail entre a conferência e o insert.
        raise AcaoRecusada(409, "já existe um usuário com esse e-mail") from exc
    auditar(
        sessao,
        autor_id,
        "usuario_criar",
        str(usuario.id),
        {"nome": nome, "email": email, "perfil": perfil},
    )
    return usuario


def editar(
    sessao: Session,
    autor_id: uuid.UUID,
    usuario_id: uuid.UUID,
    *,
    nome: str | None = None,
    email: str | None = None,
    perfil: str | None = None,
    pode_editar_agente: bool | None = None,
    pode_testar_fluxos: bool | None = None,
    cargo: str | None = None,
    observacao: str | None = None,
) -> None:
    usuario = _buscar(sessao, usuario_id)
    mudancas: dict[str, Any] = {}
    if cargo is not None:
        novo = _texto_opcional(cargo, TAMANHO_MAXIMO_CARGO, "função")
        if novo != usuario.cargo:
            mudancas["cargo"] = novo
    mudou_observacao = False
    if observacao is not None:
        nova = _texto_opcional(observacao, TAMANHO_MAXIMO_OBSERVACAO, "observação")
        mudou_observacao = nova != usuario.observacao
        usuario.observacao = nova
    if pode_testar_fluxos is not None and pode_testar_fluxos != usuario.pode_testar_fluxos:
        mudancas["pode_testar_fluxos"] = pode_testar_fluxos
    if pode_editar_agente is not None and pode_editar_agente != usuario.pode_editar_agente:
        mudancas["pode_editar_agente"] = pode_editar_agente
    if nome is not None and _validar_nome(nome) != usuario.nome:
        mudancas["nome"] = _validar_nome(nome)
    if email is not None and _validar_email(email) != usuario.email:
        mudancas["email"] = _validar_email(email)
        _email_em_uso(sessao, mudancas["email"], exceto=usuario.id)
    if perfil is not None and perfil != usuario.perfil:
        _validar_perfil(perfil)
        if usuario.perfil == "gestor":
            if usuario.id == autor_id:
                raise AcaoRecusada(409, "você não pode tirar o seu próprio perfil de gestor")
            _exigir_outro_gestor(sessao, usuario)
        mudancas["perfil"] = perfil
    if not mudancas and not mudou_observacao:
        return
    for campo, valor in mudancas.items():
        setattr(usuario, campo, valor)
    try:
        with sessao.begin_nested():
            sessao.flush()
    except IntegrityError as exc:
        raise AcaoRecusada(409, "já existe um usuário com esse e-mail") from exc
    if mudou_observacao:
        # Texto livre sobre uma pessoa: a auditoria guarda que mudou, não o quê.
        mudancas["observacao"] = "alterada"
    auditar(sessao, autor_id, "usuario_editar", str(usuario.id), mudancas)


def redefinir_senha(
    sessao: Session, autor_id: uuid.UUID, usuario_id: uuid.UUID, senha: str
) -> None:
    """Troca a senha, derruba as sessões da pessoa e zera o bloqueio.

    Liga a troca obrigatória: quem conhece a senha nova é o gestor que a
    digitou aqui. A própria senha o gestor troca em "Seu perfil", informando a
    atual (decisão 0030).
    """

    if usuario_id == autor_id:
        raise AcaoRecusada(
            409, "você não pode redefinir a sua própria senha: troque-a em Seu perfil"
        )
    _validar_senha(senha)
    usuario = _buscar(sessao, usuario_id)
    usuario.senha_hash = gerar_hash(senha)
    usuario.trocar_senha = True
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    encerrar_sessoes(sessao, usuario)
    sessao.flush()
    auditar(sessao, autor_id, "usuario_senha", str(usuario.id))


def trocar_propria_senha(
    sessao: Session, usuario_id: uuid.UUID, token: str, atual: str, nova: str
) -> bool:
    """A pessoa troca a própria senha; as outras sessões dela caem, a do `token` fica.

    Devolve False quando a senha atual não confere: a falha contada (a mesma do
    login) precisa do commit, então quem chama recusa depois de fechar a
    transação.
    """

    _validar_senha(nova)
    if nova == atual:
        raise AcaoRecusada(422, "a senha nova precisa ser diferente da atual")
    usuario = _buscar(sessao, usuario_id)
    # Relido sob a trava: quem foi desativado no meio do pedido não troca.
    if not usuario.ativo or not conferir_senha(sessao, usuario, atual):
        return False
    usuario.senha_hash = gerar_hash(nova)
    usuario.trocar_senha = False
    encerrar_outras_sessoes(sessao, usuario, token)
    sessao.flush()
    auditar(sessao, usuario.id, "usuario_senha_propria", str(usuario.id))
    return True


def desbloquear(sessao: Session, autor_id: uuid.UUID, usuario_id: uuid.UUID) -> None:
    usuario = _buscar(sessao, usuario_id)
    usuario.tentativas_falhas = 0
    usuario.bloqueado_ate = None
    sessao.flush()
    auditar(sessao, autor_id, "usuario_desbloquear", str(usuario.id))


def desativar(sessao: Session, autor_id: uuid.UUID, usuario_id: uuid.UUID) -> int:
    """Desativa e devolve à fila as conversas que a pessoa tinha assumido.

    Devolve quantas conversas voltaram para `handoff`, cada uma com o alerta
    `atendente_desativado`.
    """

    if usuario_id == autor_id:
        raise AcaoRecusada(409, "você não pode desativar a si mesmo")
    usuario = _buscar(sessao, usuario_id)
    if not usuario.ativo:
        return 0
    if usuario.perfil == "gestor":
        _exigir_outro_gestor(sessao, usuario)

    usuario.ativo = False
    encerrar_sessoes(sessao, usuario)
    sessao.flush()

    # Trava cada conversa (em ordem fixa, sem risco de deadlock) e relê sob a
    # trava: um turno ou uma transferência em curso termina antes.
    ids = sorted(
        sessao.scalars(
            select(Conversa.conversation_id).where(
                Conversa.atendimento == "assumida", Conversa.atendente_id == usuario.id
            )
        ).all()
    )
    devolvidas = 0
    for conversation_id in ids:
        conversa = travar_e_reler(sessao, conversation_id)
        if conversa.atendimento != "assumida" or conversa.atendente_id != usuario.id:
            continue
        atendimento.entrar_em_handoff(
            sessao,
            conversa,
            "atendente_desativado",
            {"usuario_id": str(usuario.id), "nome": usuario.nome},
        )
        devolvidas += 1

    auditar(sessao, autor_id, "usuario_desativar", str(usuario.id), {"conversas": devolvidas})
    return devolvidas


def reativar(sessao: Session, autor_id: uuid.UUID, usuario_id: uuid.UUID) -> None:
    usuario = _buscar(sessao, usuario_id)
    if usuario.ativo:
        return
    usuario.ativo = True
    sessao.flush()
    auditar(sessao, autor_id, "usuario_reativar", str(usuario.id))
