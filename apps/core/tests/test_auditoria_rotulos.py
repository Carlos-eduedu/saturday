"""Todo código que o core grava e o painel mostra tem rótulo em português.

Ações da auditoria na página do membro (`apps/painel/src/membros.ts`); tipos de
prova, nós do grafo e tipos de chamada externa em `apps/painel/src/rotulos.ts`.
Código sem rótulo aparece cru na tela: este teste falha antes disso.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from saturday.agent.service import RAMO_DA_OFERTA

RAIZ = Path(__file__).resolve().parents[3]
FONTES = RAIZ / "apps/core/src/saturday"
MEMBROS = RAIZ / "apps/painel/src/membros.ts"
ROTULOS = RAIZ / "apps/painel/src/rotulos.ts"


# Quem grava cada código, e em que posição ele vem (None: só por nome). Entram
# também os embrulhos que repassam o código no mesmo lugar.
AUDITAM = {"auditar": 2, "_auditar": 2, "_auditada": 2}
PROVAM = {"gravar_prova": None}
CHAMAM = {"registrar_chamada": 0, "_post_json": 1}


# Código que o teste não lê: passe o texto, ou uma constante do próprio arquivo.
LEIA = "código vindo de variável, o rótulo não é conferido"


def _literais(no: ast.expr | None, arvore: ast.Module) -> list[str] | None:
    """O código como texto; de f-string, só o prefixo fixo. None: o teste não lê."""

    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if isinstance(no, ast.JoinedStr):
        return _literais(no.values[0], arvore)
    if isinstance(no, ast.IfExp):
        a, b = _literais(no.body, arvore), _literais(no.orelse, arvore)
        return None if a is None or b is None else a + b
    if isinstance(no, ast.Name | ast.Attribute):
        # Constante do módulo (`PARCEIRO`) ou atributo (`self._parceiro`): vale
        # o que o próprio arquivo atribui a esse nome.
        nome = no.id if isinstance(no, ast.Name) else no.attr
        lidas: list[str] = []
        for atribuicao in ast.walk(arvore):
            if not isinstance(atribuicao, ast.Assign):
                continue
            alvos = {getattr(a, "id", None) or getattr(a, "attr", None) for a in atribuicao.targets}
            if nome in alvos:
                valor = _literais(atribuicao.value, arvore)
                if valor is None:
                    return None
                lidas += valor
        return lidas or None
    return None


def _gravados(funcoes: dict[str, int | None], palavra: str) -> tuple[set[str], list[str]]:
    """Os códigos gravados e as chamadas que o teste não consegue ler."""

    codigos: set[str] = set()
    ilegiveis: list[str] = []
    for arquivo in FONTES.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text())
        # Dentro de um embrulho o código é só repassado: quem o chama é conferido.
        repasses = {
            id(chamada)
            for funcao in ast.walk(arvore)
            if isinstance(funcao, ast.FunctionDef) and funcao.name in funcoes
            for chamada in ast.walk(funcao)
        }
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call) or id(no) in repasses:
                continue
            nome = getattr(no.func, "id", None) or getattr(no.func, "attr", None)
            if nome not in funcoes:
                continue
            posicao = funcoes[nome]
            codigo = no.args[posicao] if posicao is not None and len(no.args) > posicao else None
            codigo = next((k.value for k in no.keywords if k.arg == palavra), codigo)
            lidas = _literais(codigo, arvore)
            if lidas is None:
                ilegiveis.append(f"{arquivo.relative_to(RAIZ)}:{no.lineno}")
            else:
                codigos.update(lidas)
    return codigos, ilegiveis


def _nos_do_grafo() -> set[str]:
    """As chaves de `NOS` em `agent/graph.py`, de onde saem os `add_node`."""

    arvore = ast.parse((FONTES / "agent/graph.py").read_text())
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.AnnAssign)
            and getattr(no.target, "id", None) == "NOS"
            and isinstance(no.value, ast.Dict)
        ):
            chaves = no.value.keys
            # Chave que não é texto (nome, `**outro`) escaparia da conferência.
            assert all(isinstance(c, ast.Constant) for c in chaves), "NOS só com chaves literais"
            return {c.value for c in chaves if isinstance(c, ast.Constant)}
    raise AssertionError("NOS não está mais em agent/graph.py")


def _bloco(arquivo: Path, nome: str) -> str:
    achado = re.search(rf"const {nome}\b.*?= [\[{{](.*?)\n[\]}}];", arquivo.read_text(), re.DOTALL)
    assert achado, f"{nome} não está mais em {arquivo.name}"
    return achado.group(1)


def _chaves(arquivo: Path, nome: str) -> set[str]:
    return set(re.findall(r'^\s*"?([\w:]+)"?: "', _bloco(arquivo, nome), re.MULTILINE))


def test_toda_acao_da_auditoria_tem_rotulo_no_painel() -> None:
    acoes, ilegiveis = _gravados(AUDITAM, "acao")
    assert acoes, "nenhuma chamada de auditar() encontrada"
    assert not ilegiveis, f"{LEIA}: {ilegiveis}"

    exatas = _chaves(MEMBROS, "ACOES")
    prefixos = [*re.findall(r'\["([^"]+)",', _bloco(MEMBROS, "FAMILIAS")), "revelar:"]

    sem_rotulo = sorted(
        a for a in acoes if a not in exatas and not any(a.startswith(p) for p in prefixos)
    )
    assert not sem_rotulo, f"sem rótulo em {MEMBROS.name}: {sem_rotulo}"


def _confere(mapa: str, codigos: set[str], ilegiveis: list[str]) -> None:
    assert codigos, f"nenhum código de {mapa} encontrado no core"
    assert not ilegiveis, f"{LEIA}: {ilegiveis}"
    sem_rotulo = sorted(codigos - _chaves(ROTULOS, mapa))
    assert not sem_rotulo, f"sem rótulo em {mapa} ({ROTULOS.name}): {sem_rotulo}"


def test_todo_tipo_de_prova_tem_rotulo_no_painel() -> None:
    _confere("TIPOS_DE_PROVA", *_gravados(PROVAM, "tipo"))


def test_todo_no_do_grafo_tem_rotulo_no_painel() -> None:
    _confere("NOS", _nos_do_grafo(), [])


def test_todo_tipo_de_chamada_externa_tem_rotulo_no_painel() -> None:
    _confere("CHAMADAS", *_gravados(CHAMAM, "nome"))


def test_todo_ramo_da_oferta_vigente_tem_rotulo_no_painel() -> None:
    _confere("OFERTA_DO_RAMO", set(RAMO_DA_OFERTA.values()), [])
