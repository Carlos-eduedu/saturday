# 0012 — Usuários do painel: desativar, nunca apagar

- **Data:** 2026-11-12
- **Status:** aceita

## Contexto

Até aqui, usuário do painel só nascia pelo comando `saturday criar-usuario`, e
não havia como editar nem tirar alguém. A equipe quer gerir os usuários pelo
próprio painel: cadastrar, editar e excluir.

A `auditoria`, as mensagens enviadas pelo atendente, a conversa assumida e o
alerta resolvido apontam para `usuarios_painel` com `ON DELETE SET NULL`.
Apagar a linha apagaria o "quem" de toda ação passada, e o `AGENTS.md` exige
que toda ação de usuário grave quem, o quê, quando e o alvo.

## Decisão

- Uma aba **Usuários**, só para gestor: cadastrar (nome, e-mail, perfil e
  senha inicial de 12 caracteres ou mais), editar nome, e-mail e perfil,
  redefinir a senha, desbloquear, desativar e reativar.
- **Excluir é desativar** (`usuarios_painel.ativo`). Desativado não entra (o
  login recusa com a mesma resposta de senha errada), perde as sessões na hora,
  some da lista de transferir e não recebe transferência. A linha fica, e o
  histórico continua com o nome dele. Reativar desfaz.
- As conversas que a pessoa tinha assumido voltam para `handoff` (aguardando
  humano, não a IA), cada uma com o alerta `atendente_desativado`. Cada
  conversa é travada (`pg_advisory_xact_lock`, em ordem fixa) e relida antes de
  mudar.
- **Travas:** o gestor não rebaixa nem desativa a si mesmo, e nenhuma mudança
  deixa o painel sem gestor ativo (as linhas dos gestores ativos são travadas
  para a conferência valer sob concorrência).
- Redefinir a senha encerra as sessões da pessoa e zera o bloqueio. Mudar o
  perfil não derruba nada: o perfil é lido do banco a cada requisição.
- E-mail de usuário desativado não é reaproveitado no cadastro: a API recusa e
  pede para reativar.
- Usuário ganha `nome` (os que já existiam receberam o trecho do e-mail antes do
  `@`), mostrado no painel no lugar do e-mail.
- Auditoria: `usuario_criar` e `usuario_editar` (só os campos que mudaram),
  `usuario_senha`, `usuario_desbloquear`, `usuario_desativar` (com quantas
  conversas voltaram) e `usuario_reativar`. Senha e hash nunca entram.
- O comando `saturday criar-usuario` continua, para criar o primeiro gestor, e
  ganhou `--nome`.

## Alternativas descartadas

- **Apagar de verdade.** Perderia o autor da auditoria e das mensagens.
- **Convite por e-mail.** O Saturday não envia e-mail; o gestor define a senha
  inicial e a repassa. Troca obrigatória no primeiro acesso e "minha conta"
  ficam para depois.
