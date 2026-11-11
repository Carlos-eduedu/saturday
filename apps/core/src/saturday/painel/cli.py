"""`saturday criar-usuario`: o único jeito de criar usuário nesta fase."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy.exc import IntegrityError

from saturday.dados.sessao import criar_engine, criar_factory, sessao
from saturday.painel.sessoes import PERFIS, criar_usuario
from saturday.settings import get_settings

TAMANHO_MINIMO_SENHA = 12


def criar_usuario_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="saturday criar-usuario")
    parser.add_argument("--email", required=True)
    parser.add_argument("--perfil", choices=PERFIS, default="atendente")
    args = parser.parse_args(argv)

    # A senha nunca passa por argumento: ficaria no histórico do shell.
    senha = getpass.getpass("Senha: ")
    if len(senha) < TAMANHO_MINIMO_SENHA:
        print(f"A senha precisa de pelo menos {TAMANHO_MINIMO_SENHA} caracteres.", file=sys.stderr)
        return 1
    if senha != getpass.getpass("Repita a senha: "):
        print("As senhas não conferem.", file=sys.stderr)
        return 1

    engine = criar_engine(get_settings())
    try:
        with sessao(criar_factory(engine)) as aberta:
            criar_usuario(aberta, args.email, senha, args.perfil)
    except IntegrityError:
        print("Já existe usuário com esse e-mail.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Usuário criado ({args.perfil}).")
    return 0
