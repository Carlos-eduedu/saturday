# Canal oficial da Meta: o que não está na especificação

O canal segue a seção "Especificação: WhatsApp e painel" do documento da raiz;
o caminho de uma mensagem está em [`apps/core/README.md`](../apps/core/README.md).
Aqui fica o que foi além dela.

## Leitura do número (decisão 0032)

A tela Canais mostra o número exibido (mascarado) e a qualidade de cada número
de `SATURDAY_WHATSAPP_NUMEROS`. `WhatsAppClient.ler_numero` faz
`GET /{phone_number_id}` na Graph e lê `display_phone_number` e
`quality_rating`; a rota `/admin/canais` guarda cada leitura por 60 s na memória
do processo. Rota, campos, valores e as páginas da Meta consultadas estão na
[decisão 0032](decisoes/0032-leitura-do-numero-na-graph.md).

No simulador (`simuladores/meta/`), a qualidade troca assim:

```bash
curl -X POST localhost:8100/admin/numero -H 'content-type: application/json' \
  -d '{"quality_rating": "RED"}'
```

## Conferência manual: legenda e nome de arquivo (issue 31)

`enviar_midia` manda `caption` em imagem e documento e `filename` em documento.
Os testes só conferem o que sai para o simulador; falta uma pessoa ver no
celular. Uma vez, no ambiente de desenvolvimento ligado à Meta, com o próprio
celular como cliente:

1. Do celular, escreva para o número de desenvolvimento (abre a janela de 24 h).
2. No painel, assuma essa conversa.
3. Envie pelo compositor uma foto JPG com um texto junto. No celular: a foto
   chega com o texto como legenda, na mesma mensagem.
4. Envie um PDF chamado `Proposta João 1.pdf`, com um texto junto. No celular:
   o documento aparece com esse nome, com acento e espaço, e o texto como
   legenda.
5. Grave um áudio no compositor e envie. No celular: chega e toca, sem legenda
   (o Saturday não manda legenda em áudio).
6. No painel, as três mensagens ficam como entregues, sem "falhou".

Deu certo: apague o `TODO(meta)` de `enviar_midia`
(`apps/core/src/saturday/canais/whatsapp/cliente.py`) e marque o critério na
issue 31. Deu errado: anote o tipo, o que apareceu no celular e o código de
erro da mensagem no painel, e reabra a issue.
