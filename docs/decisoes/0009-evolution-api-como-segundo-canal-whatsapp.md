# 0009 — Evolution API como segundo canal de WhatsApp

- **Data:** 2026-11-12
- **Status:** aceita; a lista de instâncias e a gestão delas mudaram na
  [decisão 0010](0010-instancias-da-evolution-geridas-pelo-painel.md)
- **Desvia de:** `AGENTS.md`, regra 1 (parceiros externos: só Meta, Granatech,
  BrasilAPI, OpenRouter) e regra 12 (contratos de API descritos no documento)

## Contexto

Alguns números de WhatsApp da MEX não estão na Cloud API da Meta. A Evolution
API (v2) conecta esses números pelo WhatsApp Web (integração
`WHATSAPP-BAILEYS`), que não é oficial: não tem janela de 24 h, não tem
modelos aprovados e o número pode ser banido.

## Decisão

- A Evolution **convive** com a Meta: cada número pertence a um canal só. O
  piloto Granatech continua na Cloud API.
- Entra como canal próprio, `evolution`, ao lado de `whatsapp`, despachado pelo
  `EntregadorPorCanal` do outbox. A saída da Meta (janela e modelos) não muda.
- O mesmo celular escrevendo num número Meta e num número Evolution gera **duas
  conversas**. O reaproveitamento por CPF da Granatech vale entre elas.
- Sem janela: toda saída é texto livre, inclusive pós-venda e recontato. O
  recontato de marketing segue o mesmo opt-in (`conversas.marketing`).
- Todas as jornadas (INSS e CLT) atendem pelos dois canais; o grafo não sabe de
  canal.
- A Evolution é **instância própria do Saturday**, no profile `evolution` do
  compose, com Postgres e Redis dela. Não é a Evolution da MEX (regra 1
  continua valendo para sistemas da MEX).
- O webhook da Evolution não é assinado. Ele chega pela rede interna do compose,
  sem domínio público, com token longo num header comparado em tempo constante
  (`SATURDAY_EVOLUTION_WEBHOOK_TOKEN`), como pede a regra 10.
- Tudo atrás de `SATURDAY_EVOLUTION_ATIVO` (padrão `false`). Testes e
  desenvolvimento usam `simuladores/evolution/` (regra 11).
- Contrato permitido (regra 12), conferido no código da tag 2.3.7 e com a
  imagem fixada em `evoapicloud/evolution-api:v2.3.7`:
  `POST /message/sendText/{instancia}`,
  `POST /chat/getBase64FromMediaMessage/{instancia}` e os eventos de webhook
  `messages.upsert` e `messages.update`. A leitura fica com a configuração
  `readMessages` da instância. Qualquer outra rota entra por nova decisão.

## Alternativas descartadas

- **Integração `WHATSAPP-BUSINESS` da Evolution.** Só repassa para a Cloud API
  que o Saturday já usa: um intermediário a mais, sem ganho.
- **Canal `whatsapp` único com um campo "provedor".** Espalharia condicionais
  pela entrada, pela saída e pelo painel; a janela e os modelos são da Meta.
- **Uma conversa por celular entre os dois canais.** Exigiria decidir por qual
  número responder e permitir troca de canal no meio da jornada.
- **Usar a Evolution que a MEX já opera.** Quebra a regra 1.

## Consequências

- Risco de banimento dos números Evolution fica com a operação; mensagem
  proativa em excesso aumenta esse risco.
- O painel esconde o envio de modelo nas conversas `evolution`.
