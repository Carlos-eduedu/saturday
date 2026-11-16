"""Toda ação que o core grava na auditoria tem frase na página do membro.

A página (`apps/painel/src/membros.ts`) mostra as últimas ações de uma pessoa.
Ação sem rótulo aparece ali com o código cru: este teste falha antes disso.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
FONTES = RAIZ / "apps/core/src/saturday"
ROTULOS = RAIZ / "apps/painel/src/membros.ts"


# `auditar` e os dois embrulhos da Granatech, que repassam a ação no mesmo lugar.
AUDITAM = {"auditar", "_auditar", "_auditada"}


def _literais(no: ast.expr | None) -> list[str] | None:
    """A ação como texto; de f-string, só o prefixo fixo. None: o teste não lê."""

    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if isinstance(no, ast.JoinedStr):
        return _literais(no.values[0])
    if isinstance(no, ast.IfExp):
        a, b = _literais(no.body), _literais(no.orelse)
        return None if a is None or b is None else a + b
    return None


def _acoes_do_core() -> tuple[set[str], list[str]]:
    """As ações gravadas e as chamadas que o teste não consegue ler."""

    acoes: set[str] = set()
    ilegiveis: list[str] = []
    for arquivo in FONTES.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text())
        # Dentro de um embrulho a ação é só repassada: quem o chama é conferido.
        repasses = {
            id(chamada)
            for funcao in ast.walk(arvore)
            if isinstance(funcao, ast.FunctionDef) and funcao.name in AUDITAM
            for chamada in ast.walk(funcao)
        }
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call) or id(no) in repasses:
                continue
            nome = getattr(no.func, "id", None) or getattr(no.func, "attr", None)
            if nome not in AUDITAM:
                continue
            acao = no.args[2] if len(no.args) > 2 else None
            acao = next((k.value for k in no.keywords if k.arg == "acao"), acao)
            lidas = _literais(acao)
            if lidas is None:
                ilegiveis.append(f"{arquivo.relative_to(RAIZ)}:{no.lineno}")
            else:
                acoes.update(lidas)
    return acoes, ilegiveis


def _bloco(texto: str, nome: str) -> str:
    achado = re.search(rf"const {nome}\b.*?= [\[{{](.*?)\n[\]}}];", texto, re.DOTALL)
    assert achado, f"{nome} não está mais em {ROTULOS.name}"
    return achado.group(1)


def test_toda_acao_da_auditoria_tem_rotulo_no_painel() -> None:
    acoes, ilegiveis = _acoes_do_core()
    assert acoes, "nenhuma chamada de auditar() encontrada"
    # Ação vinda de variável: passe o texto direto na chamada, ou o rótulo não é conferido.
    assert not ilegiveis, ilegiveis

    texto = ROTULOS.read_text()
    exatas = set(re.findall(r'^\s*"?([\w:]+)"?: "', _bloco(texto, "ACOES"), re.MULTILINE))
    prefixos = [*re.findall(r'\["([^"]+)",', _bloco(texto, "FAMILIAS")), "revelar:"]

    sem_rotulo = sorted(
        a for a in acoes if a not in exatas and not any(a.startswith(p) for p in prefixos)
    )
    assert not sem_rotulo, f"sem rótulo em {ROTULOS.name}: {sem_rotulo}"
