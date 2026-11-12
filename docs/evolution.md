# Canal Evolution (WhatsApp Web)

Segundo canal de WhatsApp, ao lado da Cloud API da Meta. A decisão e os seus
limites estão em [decisoes/0009](decisoes/0009-evolution-api-como-segundo-canal-whatsapp.md).

## Como funciona

- Cada número é uma **instância** da Evolution (v2.3.7, integração Baileys). O
  nome da instância faz o papel do `phone_number_id` da Meta.
- O canal é `evolution`. A conversa é `evolution:{celular}`: o mesmo celular no
  número da Meta é outra conversa.
- Entrada: a Evolution chama `POST /webhooks/evolution` pela rede interna do
  compose, com `x-webhook-token`. O webhook grava em `eventos_recebidos`
  (`origem=evolution`, deduplicado pelo `key.id`) e responde 200; o worker
  processa como no WhatsApp da Meta (mídia para o S3 em
  `evolution/{celular}/{id}.{ext}`, áudio transcrito, foto e PDF como anexo).
- Saída: sempre texto livre, em até cinco partes. Não há janela de 24 h nem
  modelos. O recontato de marketing (`recontato_tempo_casa`) sai como o texto
  `recontato_tempo_casa_texto` de `conhecimento/clt/mensagens.yaml` e continua
  exigindo opt-in.
- Erros: timeout de leitura → incerto (1 retry no outbox); 5xx, rede e outros
  400 (instância desconectada) → temporário; número sem WhatsApp, 401 e 404 →
  permanente.
- Painel: atendente envia texto a qualquer hora; o envio de modelo não aparece.

## Variáveis

| Variável | Uso |
| --- | --- |
| `SATURDAY_EVOLUTION_ATIVO` | Liga o canal (padrão `false`) |
| `SATURDAY_EVOLUTION_URL` | `http://evolution:8080` no compose; o simulador em dev |
| `SATURDAY_EVOLUTION_API_KEY` | `AUTHENTICATION_API_KEY` da Evolution (header `apikey`) |
| `SATURDAY_EVOLUTION_WEBHOOK_TOKEN` | Token que a instância manda no webhook |
| `SATURDAY_EVOLUTION_INSTANCIAS` | Instâncias atendidas, por vírgula |
| `EVOLUTION_POSTGRES_SENHA` | Senha do Postgres próprio da Evolution |

Com o canal ligado e fora de `pytest`, faltar a chave, o token ou as instâncias
derruba a subida.

## Ligar num ambiente

1. Acrescente `evolution` em `COMPOSE_PROFILES` e preencha as variáveis acima.
   Sobem `evolution`, `evolution-postgres` e `evolution-redis`, sem porta e sem
   domínio.
2. Crie a instância e leia o QR pela própria Evolution (por exemplo com um
   túnel temporário até `evolution:8080`; o Saturday não cria instância).
3. Configure a instância:
   - `POST /settings/set/{instancia}` com `readMessages: true` (o Saturday não
     marca como lida).
   - `POST /webhook/set/{instancia}` com
     `{"webhook": {"enabled": true, "url": "http://api:8000/webhooks/evolution",
     "headers": {"x-webhook-token": "<SATURDAY_EVOLUTION_WEBHOOK_TOKEN>"},
     "byEvents": false, "base64": false,
     "events": ["MESSAGES_UPSERT", "MESSAGES_UPDATE"]}}`.
4. Acrescente o nome da instância em `SATURDAY_EVOLUTION_INSTANCIAS`, ligue
   `SATURDAY_EVOLUTION_ATIVO=true` e reinicie API e worker.

## Desenvolvimento

O `compose.override.yaml` sobe `evolution-sim` na porta 8300 e aponta
`SATURDAY_EVOLUTION_URL` para ele. Para usar, ligue o canal com a instância
`mex-sim` e os valores padrão do simulador (`chave-do-simulador`,
`token-do-simulador`).

```bash
curl -X POST localhost:8300/admin/mensagem -H 'content-type: application/json' \
  -d '{"texto": "Oi"}'
curl localhost:8300/admin/enviadas
curl -X POST localhost:8300/admin/falhas -d '{"status": 500}'   # ou {"inexistente": true}
```

## Riscos

- WhatsApp Web não é oficial: o número pode ser banido. Evite aviso proativo em
  excesso.
- Contato que chega só com `@lid` (sem telefone) é ignorado e fica no log.
