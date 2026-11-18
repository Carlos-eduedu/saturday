# 0030 — Trocar a própria senha e troca obrigatória no primeiro acesso

- **Data:** 2026-11-18
- **Status:** aceita

## Contexto

Só o gestor redefinia senhas (decisão 0012), e a senha que ele definia valia
para sempre: duas pessoas conheciam a mesma senha. A 0012 deixou "minha conta"
e a troca no primeiro acesso para depois (issue 34).

## Decisão

- **Trocar a própria senha** (`POST /admin/eu/senha`, em "Seu perfil"): a pessoa
  informa a senha atual e a nova. A nova segue a regra de sempre (12 caracteres
  ou mais) e não pode ser igual à atual.
- **Troca obrigatória** (`usuarios_painel.trocar_senha`): o cadastro e a
  redefinição pelo gestor ligam a marca. Com ela ligada, o servidor recusa
  todo o `/admin/*` com 403 "troque a senha para continuar", inclusive o SSE.
  Passam só `GET /admin/eu`, `POST /admin/eu/senha` e `POST /admin/logout`. A
  recusa mora em `usuario_logado` (`web/dependencies.py`), por onde toda rota
  do painel passa: rota nova nasce recusada, e um teste percorre todas.
- **Ao trocar:** a marca desliga, as outras sessões da pessoa caem e a atual
  continua. A auditoria grava `usuario_senha_propria`, sem senha nem hash.
- **Senha atual errada** entra na mesma contagem do login: a 5ª falha bloqueia
  por 15 minutos e derruba todas as sessões, inclusive a de quem errou. A
  resposta é sempre 422 "senha atual inválida", sem dizer quantas faltam.
- **Quem já tinha conta** não é obrigado a trocar: a coluna nasce desligada.
- **`saturday criar-usuario`** não liga a marca: quem roda o comando escolhe a
  própria senha.
- **O gestor não redefine a própria senha pela aba Usuários:** a API recusa
  com 409, como nas outras travas do gestor sobre si mesmo (decisão 0012), e a
  página dele não mostra "Redefinir senha". Ele troca em "Seu perfil",
  informando a atual: redefinir sem a senha atual deixaria uma sessão aberta
  sem dono tomar a conta de um gestor. O gestor que esqueceu a senha pede a
  outro gestor para redefinir; se for o único, cria-se outro com
  `saturday criar-usuario --perfil gestor` para redefinir a dele.

## Alternativas descartadas

- **Recusar só no painel.** Quem tem a senha provisória chamaria a API direto.
- **Lista de rotas recusadas.** Rota nova ficaria aberta por esquecimento; a
  lista é a das três que passam.
- **Contagem separada para a senha atual.** Uma sessão roubada ganharia
  tentativas sem fim para descobrir a senha.
