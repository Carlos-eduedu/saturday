# 0020 — Membro testador: conversas de teste pelo WhatsApp

- **Data:** 2026-11-15
- **Status:** aceita

## Contexto

Quem desenvolve ou opera o Saturday precisa percorrer as jornadas pelo
WhatsApp de verdade, várias vezes, sem gastar a cota da Granatech, sem criar
proposta real e sem esperar recontatos de horas ou dias.

## Decisão

- **Quem testa:** membro ativo com a permissão nova `pode_testar_fluxos`
  (ligada pelo gestor na edição do membro) e telefone no perfil (seção "Você").
  A conversa é de teste quando o telefone dela é o desse membro. O vínculo é
  conferido na hora, pelo telefone: desativar o membro ou tirar a permissão
  desliga o teste.
- **Selo e custos:** o painel marca a conversa ("Membro · Fulano") no inbox,
  no cabeçalho e nas execuções; os turnos dela ficam fora dos custos da
  Operação.
- **`/reiniciar`:** só em conversa de membro, zera o estado da jornada para
  testar de novo. Histórico e provas gravadas ficam.
- **Granatech simulada:** só em dev e homolog. A conversa de membro usa o
  simulador da Granatech (serviço interno, sem domínio), que não gasta cota
  nem cria proposta real. Em produção não há simulador: o membro segue com a
  Granatech real, com SIM e cota normais.
- **Exceção à regra 3 (consentimento):** com a Granatech simulada, a resposta
  do membro ao pedido de autorização e ao resumo da proposta vale como aceite,
  menos negação, pergunta ou pedido de mudança: nada chega à Granatech real. Os
  textos continuam sendo mostrados, e a prova é gravada com a resposta
  prefixada por "[teste de membro]". Em qualquer chamada à Granatech real, o
  SIM continua obrigatório, também para membro.
- **Isolamento do teste:** consultas, propostas e links curtos do simulador
  levam a marca `teste`; o id externo é único junto com ela (o simulador e a
  Granatech real numeram por conta própria). A cota do simulador é a do
  parceiro `granatech_teste`, fora da cota real. O simulador manda os eventos
  com token próprio (`SATURDAY_GRANATECH_SIMULADOR_WEBHOOK_TOKEN`), e o worker
  os aplica só às linhas de teste, com o cliente do simulador. A aba Bancos e
  o alerta de consulta parada ignoram as linhas de teste.
- **Infraestrutura:** o simulador roda da imagem da API, no serviço
  `granatech-simulador` (profile `simulador-granatech`), e a API recusa subir
  em produção com `SATURDAY_GRANATECH_SIMULADOR_URL`.
- **Sem esperas:** recontatos e avisos agendados de conversa de membro
  disparam no próximo ciclo do worker.

## Consequências

- `usuarios_painel` ganha `pode_testar_fluxos` (migração `d8b3f5a1c7e2`);
  consultas, propostas e links curtos da Granatech ganham `teste` (migração
  `e2a7c4b9d1f6`).
- O teto de R$ 6.999 (regra 6) vale também para membro.
