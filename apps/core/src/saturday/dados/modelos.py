"""Tabelas do Saturday.

Nove tabelas criadas na Fase 1 e duas na Fase 3 (``sessoes_painel`` e
``alertas``). ``consentimentos``, ``chamadas_externas`` e ``cota`` ainda nascem
inertes e ganham escritor nas fases 4 e 5 (ver AGENTS.md).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from saturday.dados.base import Base

# Horário do servidor do banco, não do processo: dois workers precisam concordar.
AGORA = func.now()


class Conversa(Base):
    """Uma conversa, identificada pelo ``conversation_id`` do canal."""

    __tablename__ = "conversas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    canal: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="in_progress")
    # WhatsApp: DDD + número, e o número em que o cliente escreveu por último.
    telefone: Mapped[str | None] = mapped_column(String(20), index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(32))
    # Base da janela de 24 h: a última mensagem que o cliente mandou.
    ultima_entrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Estado de atendimento (`ia`, `handoff`, `assumida`): fonte da verdade de
    # quem responde, ver docs/decisoes/0003.
    atendimento: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ia", server_default="ia", index=True
    )
    atendente_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios_painel.id", ondelete="SET NULL")
    )
    atendimento_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Último "visto" de qualquer usuário do painel: base do "não lida".
    vista_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=AGORA, onupdate=AGORA
    )


class Mensagem(Base):
    """Mensagem trocada na conversa, nas duas direções.

    A unicidade de ``(conversa_id, direcao, message_id)`` é o que garante que o
    mesmo ``message_id`` não seja processado duas vezes e que a resposta já dada
    possa ser devolvida em vez de uma resposta vazia.
    """

    __tablename__ = "mensagens"
    __table_args__ = (
        UniqueConstraint("conversa_id", "direcao", "message_id", name="uq_mensagem_por_direcao"),
        Index("ix_mensagens_conversa_criada", "conversa_id", "criada_em"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE"), nullable=False
    )
    direcao: Mapped[str] = mapped_column(String(8), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(128))
    # `wamid` da Meta: identifica a mensagem nos dois lados do canal.
    wamid: Mapped[str | None] = mapped_column(String(128), unique=True)
    status_entrega: Mapped[str | None] = mapped_column(String(16))
    # Referências no storage (`chave`, `mime_type`), nunca o conteúdo.
    anexos: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Quem escreveu: `cliente`, `ia`, `atendente` ou `sistema`.
    autor: Mapped[str] = mapped_column(String(16), nullable=False, default="ia")
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios_painel.id", ondelete="SET NULL")
    )
    conteudo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Outbox(Base):
    """Envio pendente. A linha nasce na transação do turno e é entregue depois.

    ``proxima_tentativa_em`` funciona também como lease: ao reivindicar, o worker
    empurra o horário para frente, de modo que dois workers não pegam a mesma
    linha mesmo que um deles morra no meio da entrega.
    """

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_pendentes", "entregue_em", "falhou_em", "proxima_tentativa_em"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE"), nullable=False
    )
    canal: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proxima_tentativa_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=AGORA
    )
    entregue_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Desistência: tentativas esgotadas. Diferente de entregue — nunca foi.
    falhou_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    # Janela fechada: o modelo já avisou o cliente e o texto espera ele escrever
    # depois deste horário (ver `dados/outbox.py`).
    aguardando_cliente_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class EventoRecebido(Base):
    """Fila e deduplicação de eventos de entrada.

    O webhook só grava e responde 200; o worker é quem processa. A chave única
    ``(origem, evento_id)`` impede que um reenvio da Meta vire dois turnos.
    """

    __tablename__ = "eventos_recebidos"
    __table_args__ = (
        UniqueConstraint("origem", "evento_id", name="uq_evento_origem_id"),
        Index("ix_eventos_pendentes", "processado_em", "falhou_em"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    origem: Mapped[str] = mapped_column(String(32), nullable=False)
    evento_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    falhou_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Consentimento(Base):
    """Prova de um "SIM" do cliente. Escritor entra na Fase 5."""

    __tablename__ = "consentimentos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE")
    )
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)
    texto_mostrado: Mapped[str] = mapped_column(Text, nullable=False)
    versao: Mapped[str] = mapped_column(String(32), nullable=False)
    resposta_literal: Mapped[str] = mapped_column(Text, nullable=False)
    wamid: Mapped[str | None] = mapped_column(String(128))
    cpf: Mapped[str | None] = mapped_column(String(11))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class ChamadaExterna(Base):
    """Metadados de chamada a parceiro. Nunca guarda corpo, token nem resposta."""

    __tablename__ = "chamadas_externas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE")
    )
    servico: Mapped[str] = mapped_column(String(32), nullable=False)
    metodo: Mapped[str] = mapped_column(String(8), nullable=False)
    rota: Mapped[str] = mapped_column(Text, nullable=False)
    status_http: Mapped[int | None] = mapped_column(Integer)
    duracao_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Cota(Base):
    """Consultas gastas por parceiro e por dia. Escritor entra na Fase 4."""

    __tablename__ = "cota"
    __table_args__ = (UniqueConstraint("parceiro", "dia", name="uq_cota_parceiro_dia"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parceiro: Mapped[str] = mapped_column(String(32), nullable=False)
    dia: Mapped[date] = mapped_column(Date, nullable=False)
    usadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UsuarioPainel(Base):
    """Usuário do painel da equipe."""

    __tablename__ = "usuarios_painel"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(Text, nullable=False)
    perfil: Mapped[str] = mapped_column(String(16), nullable=False, default="atendente")
    tentativas_falhas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Auditoria(Base):
    """Trilha de ação humana."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios_painel.id", ondelete="SET NULL")
    )
    acao: Mapped[str] = mapped_column(String(64), nullable=False)
    alvo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detalhe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class SessaoPainel(Base):
    """Sessão de login. O cookie leva o token; aqui fica só o sha256 dele."""

    __tablename__ = "sessoes_painel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios_painel.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Alerta(Base):
    """Algo que pede atenção da equipe; resolvido por alguém do painel."""

    __tablename__ = "alertas"
    __table_args__ = (Index("ix_alertas_abertos", "resolvido_em", "criado_em"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE")
    )
    detalhe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)
    resolvido_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios_painel.id", ondelete="SET NULL")
    )
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
