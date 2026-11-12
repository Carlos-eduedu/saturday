"""Tabelas do Saturday.

Nove tabelas criadas na Fase 1, duas na Fase 3 (``sessoes_painel`` e
``alertas``) e duas na Fase 4 (``consultas_granatech`` e
``propostas_granatech``). A Fase 5 dá escritor a ``consentimentos`` e cria
``empresas_cnpj`` e ``recontatos``; a Fase 6 cria ``links_curtos`` e a coluna
``conversas.marketing``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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
    # Etapa da jornada no fim do último turno (`triagem`, `oferta`, `inss`...):
    # cópia do estado do grafo para a lista do painel não ler checkpoint.
    etapa: Mapped[str | None] = mapped_column(String(32))
    # Mensagens de marketing: `opt_in`, `opt_out` ou nada (nunca perguntado).
    marketing: Mapped[str | None] = mapped_column(String(8))
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
    """Consultas gastas por parceiro e por dia (ver ``dados/cota.py``)."""

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


class ConsultaGranatech(Base):
    """Consulta de saldo aberta na Granatech; cada uma gastou cota.

    ``detalhe`` guarda o detalhe já normalizado, preenchido quando a consulta
    fica pronta. ``historico`` guarda todos os eventos recebidos, inclusive os
    ignorados por virem fora de ordem.
    """

    __tablename__ = "consultas_granatech"
    __table_args__ = (Index("ix_consultas_granatech_cpf", "cpf", "criada_em"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_externo: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    cpf: Mapped[str] = mapped_column(String(11), nullable=False)
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    link_termo: Mapped[str | None] = mapped_column(Text)
    detalhe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    historico: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=AGORA, onupdate=AGORA
    )


class PropostaGranatech(Base):
    """Proposta na Granatech, gravada como intenção antes do POST.

    ``estado_envio`` diz o que sabemos do POST: ``intencao`` (ainda não saiu),
    ``criada``, ``incerta`` (timeout ou 5xx: procurar na listagem antes de tentar
    de novo) ou ``falhou`` (erro comprovado). Parcela e prazo bastam para
    reconhecer a proposta na listagem; o corpo enviado não é guardado.
    """

    __tablename__ = "propostas_granatech"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    consulta_id: Mapped[int] = mapped_column(
        ForeignKey("consultas_granatech.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE")
    )
    id_externo: Mapped[str | None] = mapped_column(String(64), unique=True)
    estado_envio: Mapped[str] = mapped_column(String(16), nullable=False, default="intencao")
    valor_parcela: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    numero_parcelas: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str | None] = mapped_column(String(64))
    tipo_notificacao: Mapped[str | None] = mapped_column(String(64))
    historico: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    intencao_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=AGORA, onupdate=AGORA
    )


class EmpresaCnpj(Base):
    """Cache da BrasilAPI por CNPJ (30 dias), compartilhado por API e worker."""

    __tablename__ = "empresas_cnpj"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    dados: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    buscada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Recontato(Base):
    """Voltar a falar com o cliente numa data marcada.

    ``motivo`` é ``cota_esgotada`` (o worker dispara) ou ``tempo_casa`` (só
    gravado até a Fase 6). ``tentativas`` conta as remarcações por cota.
    """

    __tablename__ = "recontatos"
    __table_args__ = (Index("ix_recontatos_pendentes", "motivo", "quando"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    motivo: Mapped[str] = mapped_column(String(32), nullable=False)
    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feito_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class LinkCurto(Base):
    """``/l/{codigo}`` → link de biometria vigente da proposta.

    ``url`` é a última URL conhecida, usada se a Granatech não responder no clique.
    """

    __tablename__ = "links_curtos"

    codigo: Mapped[str] = mapped_column(String(16), primary_key=True)
    id_proposta: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)


class Instancia(Base):
    """Telefone fixado de uma instância da Evolution (decisão 0010).

    Não diz quais instâncias existem (quem diz é a Evolution): só guarda o
    telefone da primeira conexão, para recusar a mesma instância com outro.
    """

    __tablename__ = "instancias"

    nome: Mapped[str] = mapped_column(String(64), primary_key=True)
    telefone: Mapped[str] = mapped_column(String(16), nullable=False)
    fixado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=AGORA)
