# 0037 — Dados sem máscara por membro

- **Data:** 2026-11-23
- **Status:** aceita

## Contexto

O painel mostra CPF, telefone, e-mail e nascimento mascarados para todos, e
cada valor inteiro sai por um "Revelar" auditado, que volta a mascarar em 1
minuto. Para quem confere dados de clientes o dia todo, isso vira um clique
por campo. A gestão pediu que o gestor possa liberar, para um membro, a tela
inteira sem máscara.

## Decisão

- **Permissão por membro:** `usuarios_painel.ve_dados_completos`, desligada
  para todos. Só o gestor liga ou desliga (`PATCH /admin/gestao/usuarios/{id}`),
  para qualquer membro, inclusive ele mesmo. A mudança entra na auditoria como
  qualquer edição de membro (`usuario_editar`, com o valor novo).
- **Escopo: tudo o que o painel mascara.** Com a permissão, voltam inteiros a
  ficha do cliente, o telefone na lista e na conversa, o telefone em
  Agente (execuções) e em Operação (custos), o CPF das consultas e propostas da
  Granatech, o telefone dos colegas em Membros e Usuários e os números dos
  canais. A decisão é do servidor, por um único ponto (`privacidade.exibir`);
  a tela não desmascara nada.
- **Auditoria de leitura:** cada ficha de cliente aberta sem máscara grava
  `ver_sem_mascara` com a conversa, na mesma transação da resposta (como o
  Revelar). A ficha recarrega a cada aviso da conversa: a mesma pessoa na
  mesma conversa grava de novo só depois de 10 minutos. As listas não gravam:
  seria uma linha por recarga. A resposta da ficha diz `sem_mascara`, e a tela
  esconde o Revelar por ela, não pelo `/eu` da entrada (a permissão muda com a
  sessão aberta).
- **Continuam mascarados para todos:** a exportação da conversa (o arquivo sai
  do painel), os logs (regra 9) e a integração da Granatech (decisão 0035).
- **Na página do membro**, a permissão é um botão próprio, "Dados sem máscara",
  ao lado de Perfil e Acesso, que pede confirmação para ligar e para desligar.

## Consequências

- O princípio "mascarar é a regra, revelar é exceção auditada" (PRODUCT.md)
  passa a ter uma exceção nomeada: a permissão, concedida e retirada pelo
  gestor, com rastro por ficha aberta.
- Quem tem a permissão não vê o botão Revelar: os dados já chegam inteiros.
