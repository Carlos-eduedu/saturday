# 0002 — Um único workspace `uv` na raiz

- **Data:** 2026-11-11
- **Status:** aceita
- **Substitui:** dois projetos `uv` independentes (apps/core e simuladores)

## Contexto

Até a Fase 2 havia dois projetos `uv`: `apps/core` (a aplicação) e `simuladores`
(os simuladores de parceiros). Cada um tinha `pyproject.toml`, `uv.lock` e
`.venv` próprios. Consequências observadas:

- o CI precisava saber em qual pasta rodar, e não cobria os simuladores;
- duas resoluções de dependência podiam divergir (por exemplo, versões diferentes
  de `fastapi` entre a aplicação e o simulador que a imita);
- todo comando novo exigia `--project` explícito.

## Decisão

Um workspace na raiz (`pyproject.toml` com `[tool.uv.workspace]`) agrupando
`apps/core` e `simuladores`. Os membros mantêm o próprio `pyproject.toml`
(dependências, scripts e configuração de ferramenta), mas:

- o **`uv.lock` é único**, na raiz;
- o **`.venv` é único**, na raiz;
- `uv sync`, `uv lock` e `uv run` funcionam de dentro de qualquer membro.

A imagem Docker passa a copiar o `pyproject.toml` da raiz, o lock e o
`pyproject.toml` de cada membro, e instala **só** o pacote `saturday`
(`uv sync --package saturday --no-editable`). Sem `--no-editable`, o `uv sync`
instala o projeto por `.pth` apontando para `apps/core/src`, que não existe no
estágio de runtime — a imagem subia sem o pacote importável.

## Alternativas descartadas

- **Manter dois projetos e só ajustar o CI.** Não resolve a divergência de
  dependências nem o atrito dos comandos.
- **Workspace com lock por membro.** O `uv` não suporta: um workspace tem um
  lock só.
- **Copiar `apps/core/src` para o runtime em vez de `--no-editable`.** Funciona,
  mas carrega código-fonte na imagem e deixa a instalação dependente do caminho.

## Consequências

- Comandos antigos continuam válidos: `uv run --project apps/core …` e
  `cd apps/core && uv run pytest` seguem funcionando.
- O CI tem dois jobs (core e simuladores) e aponta o cache para `uv.lock` da raiz.
- Quem clonar o repositório roda `uv sync` **na raiz** (ou em qualquer membro).
- Rollback: restaurar os dois locks e as linhas de `COPY` do Dockerfile. Não há
  migração de dados.
