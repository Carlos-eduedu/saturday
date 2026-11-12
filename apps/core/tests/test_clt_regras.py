"""Regras e leitura do ramo CLT, sem rede nem banco."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from saturday.agent.clt import leitura, regras
from saturday.bancos.granatech.normalizacao import DetalheConsulta, Produto, Vinculo

HOJE = date(2026, 11, 11)


# ---------------------------------------------------------------- regra do SIM


@pytest.mark.parametrize("texto", ["SIM", "sim", "Sim!", "autorizo", "Aceito sim", "sim, pode"])
def test_consentimento_aceita(texto: str) -> None:
    assert leitura.consentiu(texto)


@pytest.mark.parametrize(
    "texto",
    ["ok", "pode ver", "simulação", "sim? não sei", "não, sim depois", "nao", "assim", "simm"],
)
def test_consentimento_recusa(texto: str) -> None:
    assert not leitura.consentiu(texto)


# ---------------------------------------------------------------- sim/não


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("sim", True),
        ("Sim, trabalho", True),
        ("tenho", True),
        ("não", False),
        ("Não tenho", False),
        ("nunca", False),
        ("não sei", None),
        ("sim e não", None),
        ("banana", None),
    ],
)
def test_sim_ou_nao(texto: str, esperado: bool | None) -> None:
    assert leitura.sim_ou_nao(texto) is esperado


def test_aceite_da_oferta() -> None:
    assert leitura.aceitou("quero sim")
    assert leitura.aceitou("Aceito")
    assert not leitura.aceitou("não quero")
    assert not leitura.aceitou("e se for sem seguro")


# ---------------------------------------------------------------- tempo de casa


@pytest.mark.parametrize(
    ("texto", "meses"),
    [
        ("2 anos", 24),
        ("8 meses", 8),
        ("1 ano e meio", 18),
        ("um ano e 3 meses", 15),
        ("meio ano", 6),
        ("Três anos", 36),
        ("faz tempo", None),
        ("3", None),
    ],
)
def test_tempo_de_casa(texto: str, meses: int | None) -> None:
    assert leitura.tempo_de_casa_meses(texto) == meses


# ---------------------------------------------------------------- documentos e dados


def test_cpf() -> None:
    assert leitura.cpf("001.890.049-67") == "00189004967"
    assert leitura.cpf("00189004968") is None
    assert leitura.cpf("111.111.111-11") is None
    assert leitura.cpf("meu cpf é 00189004967") is None


def test_cnpj() -> None:
    assert leitura.cnpj("11.222.333/0001-81") == "11222333000181"
    assert leitura.cnpj("11222333000182") is None
    assert leitura.cnpj("Prime Tech LTDA") is None


def test_nome_sexo_email_celular() -> None:
    assert leitura.nome_completo("Ana  Maria da Silva") == "Ana Maria da Silva"
    assert leitura.nome_completo("Ana") is None
    assert leitura.nome_completo("Ana 123") is None
    assert leitura.sexo("Feminino") == "F"
    assert leitura.sexo("sou homem") == "M"
    assert leitura.sexo("tanto faz") is None
    assert leitura.email(" Ana@Exemplo.com ") == "ana@exemplo.com"
    assert leitura.email("ana@exemplo") is None
    assert leitura.celular("(11) 98765-4321") == "11987654321"
    assert leitura.celular("+55 11 98765-4321") == "11987654321"
    assert leitura.celular("1187654321") is None
    assert leitura.data_nascimento("15/05/1990", HOJE) == date(1990, 5, 15)


def test_numero_da_lista() -> None:
    assert leitura.numero_da_lista("2", 2) == 1
    assert leitura.numero_da_lista("opção 1", 2) == 0
    assert leitura.numero_da_lista("3", 2) is None


def test_pedido_de_mudanca() -> None:
    assert leitura.pedido_de_mudanca("quero sem seguro") == leitura.Pedido(sem_seguro=True)
    assert leitura.pedido_de_mudanca("em 24 vezes") == leitura.Pedido(parcelas=24)
    assert leitura.pedido_de_mudanca("parcela de 200") == leitura.Pedido(
        valor_parcela=Decimal("200")
    )
    assert leitura.pedido_de_mudanca("R$ 250,50") == leitura.Pedido(valor_parcela=Decimal("250.50"))
    assert leitura.pedido_de_mudanca("quanto é a taxa?") is None


# ---------------------------------------------------------------- idade × prazo


def test_homem_de_36_tem_todos_os_prazos() -> None:
    assert regras.prazos_permitidos(date(1990, 5, 15), "M", HOJE) == (17, 25, 36, 48)


def test_mulher_de_55_tem_prazos_limitados() -> None:
    # Faz 57 em 2028-11-01: 17 meses (2028-04) cabe; 25 meses (2028-12) não.
    assert regras.prazos_permitidos(date(1971, 11, 1), "F", HOJE) == (17,)


def test_homem_de_55_tem_mais_prazos_que_mulher() -> None:
    assert regras.prazos_permitidos(date(1971, 11, 1), "M", HOJE) == (17, 25, 36, 48)


def test_sem_prazo_perto_do_limite_e_abaixo_de_21() -> None:
    assert regras.prazos_permitidos(date(1970, 1, 1), "F", HOJE) == ()
    assert regras.prazos_permitidos(date(2006, 1, 1), "M", HOJE) == ()


def test_recontato_tempo_casa() -> None:
    assert regras.data_recontato_tempo_casa(8, HOJE) == date(2027, 3, 11)


# ---------------------------------------------------------------- produto


def _produto(id_: str, prazo: int, seguro: bool = True) -> Produto:
    return Produto(
        id=id_,
        nome=id_,
        parcelas=(prazo,),
        taxa_mensal=Decimal("4"),
        seguro=seguro,
        margem=None,
        limite_minimo=None,
        limite_maximo=None,
        id_empresa_seguro="7" if seguro else None,
        id_produto_seguro="21" if seguro else None,
    )


def _vinculo(*produtos: Produto, margem: str = "1500", elegivel: bool = True) -> Vinculo:
    return Vinculo(
        id_margem="m1",
        margem=Decimal(margem),
        nome_empregador="Prime Tech LTDA",
        documento_empregador="11222333000181",
        elegivel_empregador=elegivel,
        produtos=produtos,
    )


def test_escolhe_maior_comissao_e_maior_prazo() -> None:
    vinculo = _vinculo(
        _produto("AA17", 17), _produto("AAA48", 48), _produto("SS36", 36, seguro=False)
    )
    produto, prazo = regras.escolher_produto(vinculo, regras.PRAZOS) or (None, 0)
    assert produto is not None and produto.id == "AAA48" and prazo == 48


def test_cmr48_ganha_de_todos() -> None:
    vinculo = _vinculo(_produto("AAA48", 48), _produto("CMR48", 36))
    escolha = regras.escolher_produto(vinculo, regras.PRAZOS)
    assert escolha is not None and escolha[0].id == "CMR48"


def test_respeita_prazo_permitido_e_sem_seguro() -> None:
    vinculo = _vinculo(_produto("AA17", 17), _produto("AAA48", 48), _produto("SS25", 25, False))
    escolha = regras.escolher_produto(vinculo, (17,))
    assert escolha is not None and escolha[0].id == "AA17"
    sem = regras.escolher_produto(vinculo, regras.PRAZOS, sem_seguro=True)
    assert sem is not None and sem[0].id == "SS25"
    assert regras.escolher_produto(vinculo, (17,), sem_seguro=True) is None


def test_prazo_desejado_vai_para_o_mais_proximo() -> None:
    vinculo = _vinculo(_produto("AA17", 17), _produto("AA25", 25), _produto("AAA36", 36))
    escolha = regras.escolher_produto(vinculo, regras.PRAZOS, prazo_desejado=24)
    assert escolha is not None and escolha[1] == 25


def test_vinculos_ofertaveis() -> None:
    bom = _vinculo(_produto("AA17", 17))
    sem_margem = _vinculo(_produto("AA17", 17), margem="0")
    inelegivel = _vinculo(_produto("AA17", 17), elegivel=False)
    detalhe = DetalheConsulta(id="c1", vinculos=(bom, sem_margem, inelegivel), pessoa=None)
    assert regras.vinculos_ofertaveis(detalhe) == [bom]


# ---------------------------------------------------------------- empresa


def _empresa(**extras: object) -> dict[str, object]:
    base: dict[str, object] = {
        "razao_social": "PRIME TECH LTDA",
        "descricao_situacao_cadastral": "ATIVA",
        "data_inicio_atividade": "2015-03-01",
        "opcao_pelo_mei": False,
        "codigo_porte": 5,
    }
    base.update(extras)
    return base


@pytest.mark.parametrize(
    ("extras", "motivo"),
    [
        ({}, None),
        ({"descricao_situacao_cadastral": "BAIXADA"}, "situacao_cadastral"),
        ({"data_inicio_atividade": "2025-06-01"}, "empresa_nova"),
        ({"opcao_pelo_mei": True}, "mei"),
        ({"codigo_porte": 1}, "microempresa"),
        ({"razao_social": "ACME LTDA EM RECUPERAÇÃO JUDICIAL"}, "situacao_juridica"),
        ({"razao_social": "MASSA FALIDA DE ACME"}, "situacao_juridica"),
        ({"razao_social": "ACME EM LIQUIDAÇÃO"}, "situacao_juridica"),
    ],
)
def test_empresa(extras: dict[str, object], motivo: str | None) -> None:
    assert regras.empresa_reprovada(_empresa(**extras), HOJE) == motivo


# ---------------------------------------------------------------- dados da proposta

BANCOS = [
    {"codigo": "001", "nome": "Banco do Brasil", "habilitado": True},
    {"codigo": "341", "nome": "Itaú", "habilitado": True},
    {"codigo": "260", "nome": "Nu Pagamentos", "habilitado": True},
    {"codigo": "237", "nome": "Bradesco", "habilitado": True},
    {"codigo": "422", "nome": "Banco Safra", "habilitado": True},
]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("solteiro", "SOLTEIRO"),
        ("Sou casada", "CASADO"),
        ("divorciado", "DIVORCIADO"),
        ("viúva", "VIUVO"),
        ("união estável", "UNIAO_ESTAVEL"),
        ("separado", "SEPARADO"),
        ("casado e solteiro", None),
        ("normal", None),
    ],
)
def test_estado_civil(texto: str, esperado: str | None) -> None:
    assert leitura.estado_civil(texto) == esperado


def test_bancos_candidatos() -> None:
    def codigos(texto: str) -> list[object]:
        return [b["codigo"] for b in leitura.bancos_candidatos(texto, BANCOS)]

    assert codigos("341") == ["341"]
    assert codigos("1") == ["001"]
    assert codigos("itau") == ["341"]
    assert codigos("Bradesco") == ["237"]
    assert codigos("banco") == ["001", "422"]
    assert codigos("caixa") == []


def test_conta() -> None:
    assert leitura.tipo_conta("corrente") == "conta_corrente"
    assert leitura.tipo_conta("Poupança") == "conta_poupanca"
    assert leitura.tipo_conta("sei lá") is None
    assert leitura.agencia("1234") == ("1234", "")
    assert leitura.agencia("1234-x") == ("1234", "X")
    assert leitura.agencia("agência 12") is None
    assert leitura.conta_com_digito("12345-6") == ("12345", "6")
    assert leitura.conta_com_digito("123456") == ("12345", "6")
    assert leitura.conta_com_digito("conta 1") is None


def test_marketing_e_cancelamento() -> None:
    assert leitura.nao_quer_receber("Não quero receber")
    assert not leitura.nao_quer_receber("quero receber")
    assert leitura.pediu_cancelamento("quero cancelar")
    assert leitura.pediu_cancelamento("desisti")
    assert not leitura.pediu_cancelamento("quando cai o dinheiro?")


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # Conversa do dev: "Eu sou efetivado" reprovava como se fosse "sim".
        ("Eu sou efetivado", False),
        ("sou efetivo", False),
        ("sou CLT normal", False),
        ("não, sou efetivado", False),
        ("não sou estagiário", False),
        ("nenhum", False),
        ("não", False),
        ("sim", True),
        ("sou estagiário", True),
        ("estou em aviso prévio", True),
        ("sim, estou de licença maternidade", True),
        ("não sei", None),
        ("sou", None),
        ("oi", None),
    ],
)
def test_leitura_do_contrato_especial(texto: str, esperado: bool | None) -> None:
    assert leitura.contrato_especial(texto) is esperado
