# 0019 — Barra nova do painel, Membros, Operação e o último canal ativo

- **Data:** 2026-11-15
- **Status:** aceita; em 2026-11-18 a seção da Meta ganhou a qualidade e o
  número exibido pela [0032](0032-leitura-do-numero-na-graph.md) (a gestão dos
  números continua fora do painel)

## Contexto

O gestor pediu para reorganizar a navegação do painel: agrupar melhor as
funções, preparar a entrada de novos bancos e deixar mais claro o cuidado com
canais, pessoas e custos.

## Decisão

- **Menu:** Conversas · Bancos · Agente · Canais · Membros · Operação. Os
  endereços antigos (`/granatech`, `/usuarios`, `/custos`) redirecionam. Os
  alertas saem do menu: o ícone do usuário no topo mostra a contagem e abre a
  conta (seu perfil, alertas e sair), à vista também no celular.
- **Bancos:** uma seção por banco ligado (`/bancos/granatech`). Continua sem
  interface `Banco` no código até o segundo banco (decisão 0004).
- **Membros:** a aba é de todos. A seção "Você" deixa cada pessoa editar o
  próprio nome de exibição, telefone e foto. E-mail e perfil continuam só com o
  gestor, porque o e-mail é o login. A foto fica no storage privado
  (`painel/usuarios/{id}/...`) e é servida pela API só para quem entrou. A
  auditoria guarda o nome dos campos mudados, nunca o telefone. O gestor vê
  também a equipe, com um único "Adicionar usuário" que abre um diálogo.
- **Operação:** substitui Custos e junta o uso da cota da Granatech (mês, hoje
  e por dia, contra os tetos) aos relatórios de custos operacionais.
- **Canais:** um resumo dos canais ativos no topo. Ativo é número da Meta
  configurado ou instância da Evolution conectada. A API recusa (409)
  desconectar ou apagar a instância que é o único canal ativo.
- **Meta pelo painel fica para depois.** Criar, editar e excluir canais
  oficiais e conectar uma conta da Meta exigiriam guardar o token no banco
  (regra 8) e usar rotas da Meta fora da especificação (regra 12). Enquanto
  isso, a seção da Meta segue só leitura.

## Consequências

- A tabela `usuarios_painel` ganha `telefone` e `foto_chave` (migração
  `c6d2a9e4f1b7`).
- Em ambiente sem número da Meta, a última instância conectada da Evolution
  não sai pelo painel: conecte outra antes.
