"""Fumaça dos comandos do membro testador contra a pilha local (decisão 0024).

Chamado pelo `infra/fumaca_membro.sh`, com a API, o worker e os simuladores no
ar. `membro` cria o testador no banco; `conversa` manda os comandos pelo
simulador da Meta e confere as respostas que o Saturday enviou de volta.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

META = "http://127.0.0.1:8100"
TELEFONE = "11987654321"
# (comando, trecho esperado em alguma resposta, segundos de espera)
ROTEIRO = [
    ("/ajuda", "/ir <etapa>", 20),
    ("/ir identificacao", "CPF", 20),
    ("/cenario sem_margem", "sem_margem", 20),
    ("/ir consultando", "", 20),
    ("/estado", "Etapa: nao_elegivel", 40),
    ("/reiniciar", "reiniciada", 20),
    ("/ir oferta", "", 20),
    ("/estado", "Etapa: oferta", 40),
    ("/humano", "atendimento humano", 20),
    ("/devolver", "devolvida", 20),
]


def membro() -> None:
    from saturday.dados.modelos import UsuarioPainel
    from saturday.dados.sessao import criar_engine, criar_factory
    from saturday.dados.sessao import sessao as abrir
    from saturday.painel import sessoes
    from saturday.settings import get_settings
    from sqlalchemy import update

    fabrica = criar_factory(criar_engine(get_settings()))
    with abrir(fabrica) as s:
        usuario = sessoes.criar_usuario(
            s, "membro@exemplo.test", "senha-de-fumaca-local", "gestor", "Membro Fumaça"
        )
        s.execute(
            update(UsuarioPainel)
            .where(UsuarioPainel.id == usuario.id)
            .values(telefone=TELEFONE, pode_testar_fluxos=True)
        )


def _json(caminho: str, corpo: dict[str, object] | None = None) -> dict[str, object]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(
        META + caminho, data=dados, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(pedido, timeout=15) as resposta:
        cru = resposta.read()
    return json.loads(cru) if cru else {}


def _textos() -> list[str]:
    enviadas = _json("/admin/enviadas")["enviadas"]
    assert isinstance(enviadas, list)
    return [str((e.get("text") or {}).get("body") or "") for e in enviadas]


def conversa() -> None:
    for comando, esperado, prazo in ROTEIRO:
        fim = time.monotonic() + prazo
        while True:
            antes = len(_textos())
            _json("/admin/mensagem", {"numero": TELEFONE, "texto": comando})
            novos: list[str] = []
            # O worker entrega em ciclos: espera a resposta deste comando chegar.
            while time.monotonic() < fim and not novos:
                time.sleep(1)
                novos = _textos()[antes:]
            if any(esperado.lower() in t.lower() for t in novos):
                print(f"ok    {comando}")
                break
            # `/estado` repete até a jornada chegar lá (o resultado vem por webhook).
            if comando != "/estado" or time.monotonic() >= fim:
                print(f"FALHA {comando}: esperava {esperado!r}, veio {novos!r}")
                sys.exit(1)
            time.sleep(2)
    print("fumaça do membro testador: tudo certo")


if __name__ == "__main__":
    {"membro": membro, "conversa": conversa}[sys.argv[1]]()
