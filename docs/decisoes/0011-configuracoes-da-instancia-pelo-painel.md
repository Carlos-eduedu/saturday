# 0011 — Configurações da instância ajustadas pelo painel

- **Data:** 2026-11-12
- **Status:** aceita
- **Altera:** [decisão 0010](0010-instancias-da-evolution-geridas-pelo-painel.md)
  (o que criar e reconectar reaplicam; contrato permitido)

## Contexto

A equipe não tem acesso direto à Evolution: ela fica na rede interna, sem
domínio (0010). Para conferir e ajustar uma instância, só resta o painel. Na
0010, reconectar regravava as seis configurações com o padrão do Saturday, o
que apagaria qualquer ajuste feito pela equipe.

## Decisão

- **Detalhes** na tela Canais lê o webhook e as configurações gravados na
  instância e mostra cada um ao lado do padrão do Saturday. O token do webhook
  nunca sai da API: o painel vê só se ele confere, difere ou falta.
- **Divergência é só do webhook**: sem ele o Saturday não recebe nada. O gestor
  regrava o webhook do Saturday a qualquer momento, sem desconectar.
- **As configurações são do gestor**: recusar chamadas (com a mensagem),
  ignorar grupos, sempre online, marcar como lida, ler status e sincronizar o
  histórico. Criar aplica o padrão; reconectar regrava **só o webhook** e deixa
  as configurações como estão. A tela oferece "usar o padrão do Saturday".
- Salvar parte do que está gravado: o `/settings/set` da 2.3.7 exige os seis
  booleanos e tira da memória da instância o que não vier (`msgCall`,
  `wavoipToken`). O `wavoipToken` nunca passa pelo painel.
- Cada ajuste grava `auditoria` (`canal_configurar`, com os valores;
  `canal_webhook`).
- Contrato somado ao da 0010, conferido no código da tag 2.3.7:
  `GET /webhook/find/{instancia}` e `GET /settings/find/{instancia}`.

## Alternativas descartadas

- **Editar URL, token e eventos do webhook.** Qualquer valor diferente do do
  Saturday só quebra a entrada; basta regravar o certo.
- **Guardar as configurações no Saturday e reaplicar a cada reconexão.**
  Duplicaria o que a Evolution já guarda e teria de ficar em sincronia.
