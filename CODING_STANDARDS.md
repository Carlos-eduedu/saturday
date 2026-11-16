# Padrões de revisão

Lido na revisão de um diff, não durante a implementação. Só entram aqui
julgamentos que nenhum linter confere; o que é mecânico vira checagem no CI.

## Painel (`apps/painel`)

- **`DESIGN.md` acompanha o código.** Um diff que muda cor, tamanho, texto,
  navegação ou o que uma tela mostra, e com isso contradiz o `DESIGN.md`,
  atualiza o `DESIGN.md` no mesmo commit. Decisão consciente de divergir fica
  escrita lá, com o motivo.

## Testes do core (`apps/core/tests`)

- **Login do painel só pelo `conftest`.** Teste que entra no painel usa `entrar`
  ou `entrar_como` e a `SENHA_DO_PAINEL`; um `_entrar` ou `_login` próprio no
  arquivo de teste é duplicação.
