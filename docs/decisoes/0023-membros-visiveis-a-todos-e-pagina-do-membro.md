# 0023 — A equipe é visível a todos, e cada membro tem a sua página

- **Data:** 2026-11-16
- **Status:** aceita
- **Altera:** a parte "Membros" da 0019 (a equipe era só do gestor)

## Contexto

A aba Membros mostrava, por pessoa, nome, e-mail, perfil, situação e cadastro, e
só para o gestor. O atendente não via colega nenhum, nem na hora de transferir
uma conversa. O gestor pediu para ampliar os dados dos membros e rever quais são
necessários.

## Decisão

- **Lista para todos (`/membros`).** Do colega aparece só o que serve para
  transferir: nome, foto, função, perfil, estado e conversas assumidas agora.
- **Página do membro (`/membros/:id`).** A própria pessoa e o gestor veem também
  contato, último acesso, a atividade dos últimos 7 dias (mensagens enviadas,
  conversas assumidas, devolvidas e transferidas) e as últimas 10 ações. Só o
  gestor vê situação, bloqueio e observação, e faz a gestão ali; o diálogo
  "Editar" deixa de existir.
- **Quem vê o quê é decidido no servidor** (`web/api/membros.py`): o campo que a
  pessoa não pode ver não sai na resposta.
- **Dados pessoais:** o telefone do colega não vai para o atendente, nem
  mascarado. Para o gestor ele continua mascarado.
- **Estado:** `ausente` (a própria pessoa marcou), `disponivel` (usou o painel
  há menos de 5 min) ou `fora`. A sessão dura 8 h, então sessão aberta não diz se
  a pessoa está no painel. O último acesso é regravado no máximo uma vez por
  minuto.
- **Disponibilidade é informação, não bloqueio.** A lista de destinos do
  "Transferir" mostra o estado; transferir para um ausente continua permitido.
  Handoff, alertas e a IA não mudam.
- **Função e observação são do gestor.** A auditoria guarda que a observação
  mudou, nunca o texto.
- **As últimas ações mostram o tipo, a hora e a conversa**, nunca o `detalhe`
  gravado na auditoria.

## Consequências

- `usuarios_painel` ganha `cargo`, `observacao`, `disponivel` e
  `ultimo_acesso_em` (migração `f3b6d9a2c5e8`).
- Todo pedido autenticado pode escrever em `usuarios_painel` (no máximo uma vez
  por minuto por pessoa).
- "No painel" inclui a aba aberta em segundo plano, que segue pedindo dados.
- Desativado continua existindo só para o gestor (decisão 0012).
- Fora do escopo: escala, horário de trabalho, metas e filtrar a fila pelas
  conversas de um colega.
