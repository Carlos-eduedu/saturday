# 0001 — O outbox é o único dono do reagendamento

- **Data:** 2026-11-11
- **Status:** aceita
- **Substitui:** o retry interno do canal WhatsApp (Fase 2)

## Contexto

Na Fase 2 o canal WhatsApp tinha a própria escada de retry (2 s, 5 s, 10 s) e o
outbox também reagendava (`max_tentativas = 8`). Um erro temporário podia ser
tentado três vezes dentro da mesma entrega e mais oito pelo outbox — até 24
tentativas — sem que ninguém soubesse qual camada era responsável por desistir.
Também não havia como distinguir "com certeza não saiu" de "talvez tenha saído":
a Meta **não** oferece chave de idempotência para envio de mensagem, então
repetir um timeout de leitura pode duplicar a mensagem no celular do cliente.

## Decisão

O canal **só classifica** e para. O resultado de uma entrega é um dos:

| Resultado | Quando | O que o outbox faz |
| --- | --- | --- |
| `ok` | enviado | fecha a linha |
| `temporario` | 5xx, erro de rede, códigos transitórios | backoff e nova tentativa |
| `temporario_incerto` | timeout de leitura / conexão caída depois do envio | no máximo **1** nova tentativa |
| `permanente` | 4xx de conteúdo ou credencial | desiste na hora |
| `janela_fechada` | a Meta recusou texto com `131047` | converte para modelo na mesma tentativa |

O reagendamento é exclusivamente do outbox:

- backoff exponencial com jitter: `base × 2^(n−1) × U(0,5; 1,5)`, teto de 300 s;
- **no máximo 6 tentativas** (`SATURDAY_OUTBOX_MAX_TENTATIVAS`);
- esgotado, a linha recebe `falhou_em` (diferente de entregue) e sai um log
  estruturado em `ERROR` (`outbox_desistiu`);
- `janela_fechada` não gasta tentativa extra: a conversão acontece no mesmo
  laço, chamando o entregador com `permitir_modelo=True`.

## Alternativas descartadas

- **Retry só no canal.** Simples, mas morre com o processo: a mensagem some sem
  rastro. O outbox é durável; o canal não.
- **Retry só no outbox, sem distinguir o incerto.** Duplica mensagem quando a
  Meta aceita e a resposta se perde — o cliente recebe duas vezes.
- **Chave de idempotência no envio.** Seria a solução correta; a Meta não
  oferece esse campo na Cloud API.

## Consequências

- Um único lugar decide esperar/desistir, e um único lugar registra o motivo.
- "Alerta" hoje é log em `ERROR`: a tabela de alertas do painel chega na Fase 3,
  que passa a consumir esse evento em vez de inventar outro.
- **Limitação conhecida:** mensagem dividida em partes pode duplicar as partes já
  enviadas se uma parte do meio falhar. O risco é inerente a envio sem
  idempotência; a mitigação possível seria marcar parte a parte, o que ainda não
  se justifica pelo volume do piloto.
- O webhook (canal `webhook`, não WhatsApp) mapeia qualquer falha para
  `temporario`, preservando o comportamento da Fase 1: um webhook que falha é
  reentregue.
