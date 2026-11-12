"""Outbox: o único dono do reagendamento.

O canal só devolve `Resultado`; aqui se prova a espera, o teto de tentativas, a
conversão para modelo e o limite de uma nova tentativa no caso incerto.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import Resultado
from saturday.canais.whatsapp import partes as modulo_partes
from saturday.canais.whatsapp.cliente import ErroTemporario
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.dados import outbox as fila
from saturday.dados import repositorios
from saturday.dados.modelos import Mensagem, Outbox
from saturday.jobs.outbox import ESPERA_MAXIMA_S, JITTER, drenar
from saturday.settings import Settings

# Data no passado: vence o lease e destrava a linha para o próximo lote.
PASSADO = datetime(2000, 1, 1, tzinfo=UTC)


class EntregadorFalso:
    """Devolve os resultados na ordem, registrando se pediram modelo."""

    def __init__(self, resultados: list[Resultado] | None = None) -> None:
        self.resultados = list(resultados or [])
        self.chamadas: list[bool] = []

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        self.chamadas.append(permitir_modelo)
        if not self.resultados:
            return Resultado.TEMPORARIO
        return self.resultados.pop(0)


def _enfileirar(fabrica: sessionmaker[Session], conversa: str) -> int:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa)
        linha = fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="whatsapp",
            payload={"conversation_id": conversa, "answer": "oi"},
        )
        sessao.commit()
        return linha.id


def _liberar(fabrica: sessionmaker[Session], linha_id: int) -> None:
    with fabrica() as sessao:
        sessao.execute(
            update(Outbox).where(Outbox.id == linha_id).values(proxima_tentativa_em=PASSADO)
        )
        sessao.commit()


def _estado(fabrica: sessionmaker[Session], linha_id: int) -> tuple[Any, ...]:
    with fabrica() as sessao:
        linha = sessao.get(Outbox, linha_id)
        assert linha is not None
        return (
            linha.entregue_em,
            linha.falhou_em,
            linha.tentativas,
            linha.proxima_tentativa_em,
        )


def test_ok_marca_entregue(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    assert drenar(fabrica, EntregadorFalso([Resultado.OK]), settings) == 1

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    assert tentativas == 1


def test_temporario_volta_para_a_fila(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    drenar(fabrica, EntregadorFalso([Resultado.TEMPORARIO]), settings)

    entregue_em, falhou_em, tentativas, proxima = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is None
    assert tentativas == 1
    assert proxima > datetime.now(UTC)


def test_backoff_cresce_com_jitter_dentro_da_faixa(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    """Base 2 s: 1ª espera em [1;3], 2ª em [2;6], 3ª em [4;12]."""

    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    esperas: list[float] = []
    for _ in range(3):
        drenar(fabrica, entregador, settings)
        _, _, _, proxima = _estado(fabrica, linha_id)
        esperas.append((proxima - datetime.now(UTC)).total_seconds())
        _liberar(fabrica, linha_id)

    base = settings.outbox_backoff_base_s
    for numero, espera in enumerate(esperas, start=1):
        exponencial = base * 2 ** (numero - 1)
        assert exponencial * (1 - JITTER) - 1 <= espera <= exponencial * (1 + JITTER) + 1


def test_permanente_desiste_na_primeira(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    drenar(fabrica, EntregadorFalso([Resultado.PERMANENTE]), settings)

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is not None
    assert tentativas == 1


def test_incerto_tenta_no_maximo_uma_vez_a_mais(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso([Resultado.TEMPORARIO_INCERTO, Resultado.TEMPORARIO_INCERTO])

    drenar(fabrica, entregador, settings)
    _, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert falhou_em is None  # ainda vale uma tentativa
    assert tentativas == 1

    _liberar(fabrica, linha_id)
    drenar(fabrica, entregador, settings)

    _, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert falhou_em is not None  # a segunda incerteza encerra
    assert tentativas == 2


def test_janela_fechada_converte_para_modelo(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso([Resultado.JANELA_FECHADA, Resultado.OK])

    drenar(fabrica, entregador, settings)

    assert entregador.chamadas == [False, True]
    # A conversão acontece na mesma tentativa: não consome o orçamento.
    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    assert tentativas == 1


def test_desiste_depois_do_limite_de_tentativas(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    for _ in range(settings.outbox_max_tentativas):
        drenar(fabrica, entregador, settings)
        _liberar(fabrica, linha_id)

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is not None
    assert tentativas == settings.outbox_max_tentativas
    assert settings.outbox_max_tentativas == 6


def test_espera_nunca_passa_do_teto(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    for _ in range(5):
        drenar(fabrica, entregador, settings)
        _liberar(fabrica, linha_id)

    _, _, _, proxima = _estado(fabrica, linha_id)
    espera = (proxima - datetime.now(UTC)).total_seconds()
    assert espera <= ESPERA_MAXIMA_S + 1


def test_dois_workers_nao_pegam_a_mesma_linha(
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    """`FOR UPDATE SKIP LOCKED`: cada worker reserva um conjunto disjunto."""

    _enfileirar(fabrica, conversa + "-a")
    _enfileirar(fabrica, conversa + "-b")

    with fabrica() as um, fabrica() as dois:
        primeira = fila.reivindicar(um, 1)
        segunda = fila.reivindicar(dois, 1)
        um.commit()
        dois.commit()

    assert len(primeira) == 1
    assert len(segunda) == 1
    assert primeira[0].id != segunda[0].id


def test_conversa_sem_envio_nao_drena_nada(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    with fabrica() as sessao:
        repositorios.obter_ou_criar_conversa(sessao, conversa)
        sessao.commit()

    assert drenar(fabrica, EntregadorFalso(), settings) == 0


def test_linhas_pendentes_continuam_visiveis(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    _enfileirar(fabrica, conversa)
    drenar(fabrica, EntregadorFalso([Resultado.TEMPORARIO]), settings)

    with fabrica() as sessao:
        pendentes = sessao.scalars(select(Outbox).where(Outbox.entregue_em.is_(None))).all()
    assert len(pendentes) == 1


def _cliente_escreveu(fabrica: sessionmaker[Session], conversa: str) -> None:
    with fabrica() as sessao:
        linha = repositorios.buscar_conversa(sessao, conversa)
        assert linha is not None
        repositorios.marcar_entrada(linha)
        sessao.commit()


def test_aguardando_cliente_so_volta_quando_ele_escreve(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso([Resultado.AGUARDANDO_CLIENTE, Resultado.OK])

    assert drenar(fabrica, entregador, settings) == 1
    _liberar(fabrica, linha_id)
    # O modelo já avisou: sem mensagem nova do cliente, a linha não sai.
    assert drenar(fabrica, entregador, settings) == 0

    _cliente_escreveu(fabrica, conversa)
    assert drenar(fabrica, entregador, settings) == 1

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    # A espera zerou as tentativas: a entrega do texto foi a primeira.
    assert tentativas == 1


class ClienteGraphFalso:
    """Envia texto e modelo; falha nas chamadas de texto indicadas (1, 2, ...)."""

    def __init__(self, falhar_em: set[int] | None = None) -> None:
        self.falhar_em = falhar_em or set()
        self.textos: list[str] = []
        self.modelos: list[str] = []
        self.sufixos: list[str | None] = []
        self._chamadas = 0

    def enviar_texto(self, phone_number_id: str, numero: str, texto: str) -> str:
        self._chamadas += 1
        if self._chamadas in self.falhar_em:
            raise ErroTemporario("status=503")
        self.textos.append(texto)
        return f"wamid.{self._chamadas}"

    def enviar_modelo(self, phone_number_id: str, numero: str, modelo: Any, **_extras: Any) -> str:
        self.modelos.append(modelo.nome)
        self.sufixos.append(_extras.get("sufixo_link"))
        return "wamid.modelo"


def _enfileirar_whatsapp(fabrica: sessionmaker[Session], conversa: str, texto: str) -> int:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa, canal="whatsapp")
        linha = fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="whatsapp",
            payload={
                "conversation_id": conversa,
                "numero": "11987654321",
                "phone_number_id": "p1",
                "answer": texto,
            },
        )
        sessao.commit()
        return linha.id


def test_nova_tentativa_nao_repete_partes_ja_enviadas(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modulo_partes, "INTERVALO_ENTRE_PARTES_S", 0)
    linha_id = _enfileirar_whatsapp(fabrica, conversa, "um\n\ndois\n\ntrês")
    _cliente_escreveu(fabrica, conversa)
    cliente = ClienteGraphFalso(falhar_em={2})
    saida = SaidaWhatsApp(cliente, fabrica, settings)  # type: ignore[arg-type]

    drenar(fabrica, saida, settings)
    _liberar(fabrica, linha_id)
    drenar(fabrica, saida, settings)

    assert cliente.textos == ["um", "dois", "três"]
    assert _estado(fabrica, linha_id)[0] is not None


def test_janela_fechada_avisa_uma_vez_por_conversa(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    primeira = _enfileirar_whatsapp(fabrica, conversa, "primeira\n\ncom parágrafo")
    segunda = _enfileirar_whatsapp(fabrica, conversa, "segunda")
    cliente = ClienteGraphFalso()
    saida = SaidaWhatsApp(cliente, fabrica, settings)  # type: ignore[arg-type]

    drenar(fabrica, saida, settings)

    # Um aviso só, e nenhum texto: as duas respostas esperam o cliente.
    assert cliente.modelos == ["atualizacao_pedido"]
    assert cliente.textos == []
    with fabrica() as sessao:
        linhas = sessao.scalars(select(Outbox).where(Outbox.id.in_([primeira, segunda]))).all()
        assert all(linha.aguardando_cliente_desde is not None for linha in linhas)
        assert all(linha.entregue_em is None for linha in linhas)


@pytest.mark.parametrize(
    ("extras", "modelo", "sufixo"),
    [
        (
            {"modelo_aviso": "assinatura_pronta", "link_aviso": "abc123"},
            "assinatura_pronta",
            "abc123",
        ),
        ({"modelo_aviso": "pagamento_confirmado"}, "pagamento_confirmado", None),
        # Modelo de link sem o código não fecha: sai o genérico.
        ({"modelo_aviso": "assinatura_refazer"}, "atualizacao_pedido", None),
    ],
)
def test_janela_fechada_usa_o_modelo_do_aviso(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
    extras: dict[str, str],
    modelo: str,
    sufixo: str | None,
) -> None:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa, canal="whatsapp")
        fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="whatsapp",
            payload={
                "conversation_id": conversa,
                "numero": "11987654321",
                "phone_number_id": "p1",
                "answer": "texto completo do aviso",
                **extras,
            },
        )
        sessao.commit()
    cliente = ClienteGraphFalso()
    drenar(fabrica, SaidaWhatsApp(cliente, fabrica, settings), settings)  # type: ignore[arg-type]

    assert cliente.modelos == [modelo]
    assert cliente.sufixos == [sufixo]
    assert cliente.textos == []


def test_modelo_do_painel_sai_como_modelo_e_fecha_a_linha(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa, canal="whatsapp")
        mensagem_id = repositorios.registrar_saida(
            sessao, linha_conversa, conteudo="[modelo pagamento_confirmado]", autor="atendente"
        )
        linha = fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="whatsapp",
            payload={
                "conversation_id": conversa,
                "numero": "11987654321",
                "phone_number_id": "p1",
                "answer": "",
                "modelo": "pagamento_confirmado",
                "mensagem_id": mensagem_id,
            },
        )
        sessao.commit()
        linha_id = linha.id
    cliente = ClienteGraphFalso()

    drenar(fabrica, SaidaWhatsApp(cliente, fabrica, settings), settings)  # type: ignore[arg-type]

    # Modelo escolhido no painel não espera o cliente, mesmo com a janela fechada.
    assert cliente.modelos == ["pagamento_confirmado"]
    assert _estado(fabrica, linha_id)[0] is not None
    with fabrica() as sessao:
        assert sessao.get(Mensagem, mensagem_id).wamid == "wamid.modelo"
