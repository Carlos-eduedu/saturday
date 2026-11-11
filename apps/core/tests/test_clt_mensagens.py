"""Mensagens fixas do CLT: toda chave usada existe e toda variável é preenchida."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from saturday.agent.clt import mensagens, nos

FONTES = Path(__file__).resolve().parents[1] / "src" / "saturday"
# `texto("chave")` e os atalhos do nó que recebem a chave direto.
CHAMADA = re.compile(r"""(?:texto|erro|nao_elegivel)\(\s*["']([a-z_]+)["']""")


def _chaves_usadas() -> set[str]:
    usadas: set[str] = set()
    for arquivo in FONTES.rglob("*.py"):
        conteudo = arquivo.read_text(encoding="utf-8")
        if "mensagens" in conteudo:
            usadas |= set(CHAMADA.findall(conteudo))
    # Chaves guardadas em tabelas do nó (perguntas e reprovações da triagem).
    usadas |= set(nos.PERGUNTAS.values())
    usadas |= {chave for _, chave in nos.REPROVA.values()}
    return usadas


def test_toda_chave_usada_existe() -> None:
    usadas = _chaves_usadas()
    assert usadas, "nenhuma chamada a texto() encontrada"
    assert usadas <= mensagens.chaves().keys()


def test_toda_chave_existente_e_usada() -> None:
    sobrando = mensagens.chaves().keys() - _chaves_usadas()
    assert not sobrando, f"mensagens sem uso: {sorted(sobrando)}"


def test_cada_mensagem_renderiza_com_suas_variaveis() -> None:
    for chave, modelo in mensagens.chaves().items():
        valores = dict.fromkeys(mensagens.variaveis(modelo), "X")
        assert "{" not in mensagens.texto(chave, **valores)


def test_variavel_faltando_levanta_erro() -> None:
    with pytest.raises(KeyError):
        mensagens.texto("confirmar_celular")


def test_textos_obrigatorios_do_contrato() -> None:
    assert (
        "Vou usar os dados do seu emprego para encontrar, entre os bancos parceiros "
        "da MEX, a melhor condição para você." in mensagens.texto("abertura")
    )
    assert mensagens.texto("consentimento") == (
        "Para eu ver quanto você tem disponível, preciso da sua autorização para o "
        "banco consultar os dados do seu emprego (empresa, salário e margem) no "
        "sistema do governo. É só a consulta, não contrata nada. Você autoriza? "
        "Responda SIM."
    )
    oferta = mensagens.texto(
        "oferta",
        nome="Ana",
        liberado="4.619,53",
        n=36,
        parcela="300,00",
        taxa="4,00",
        cet="4,98",
        seguro="503,32",
    )
    assert oferta == (
        "Boa notícia, Ana! Consegui uma condição para você: R$ 4.619,53 liberados na "
        "sua conta, em 36 parcelas de R$ 300,00 descontadas no salário. Taxa de "
        "4,00% a.m. (CET de 4,98% a.m.). Já inclui o seguro Super Proteção "
        "(R$ 503,32), que cobre desemprego, morte e invalidez. Ele é opcional: se "
        "preferir sem seguro, é só me dizer que eu refaço a simulação. Quer seguir "
        "com essa proposta?"
    )


def test_versao_presente() -> None:
    assert mensagens.versao()
