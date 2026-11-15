# 0020 — Membro testador: conversas de teste pelo WhatsApp

- **Data:** 2026-11-15
- **Status:** aceita (entregas em andamento)

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
- **Exceção à regra 3 (consentimento):** com a Granatech simulada, a conversa
  de membro segue sem o "SIM", porque nada chega à Granatech real. A prova é
  gravada como "teste de membro". Em qualquer chamada à Granatech real, o SIM
  continua obrigatório, também para membro.
- **Sem esperas:** recontatos e avisos agendados de conversa de membro
  disparam no próximo ciclo do worker.

## Consequências

- `usuarios_painel` ganha `pode_testar_fluxos` (migração `d8b3f5a1c7e2`).
- O teto de R$ 6.999 (regra 6) vale também para membro.
