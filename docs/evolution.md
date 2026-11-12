# Canal Evolution (WhatsApp Web)

Segundo canal de WhatsApp, ao lado da Cloud API da Meta. As decisões e os seus
limites estão em [decisoes/0009](decisoes/0009-evolution-api-como-segundo-canal-whatsapp.md)
e [decisoes/0010](decisoes/0010-instancias-da-evolution-geridas-pelo-painel.md).

## Como funciona

- Cada número é uma **instância** da Evolution (v2.3.7, integração Baileys). O
  nome da instância faz o papel do `phone_number_id` da Meta. O Saturday atende
  toda instância da sua Evolution; o gestor as cria e conecta na tela
  **Canais** do painel.
- Telefone fixado: na primeira conexão o Saturday guarda o telefone da
  instância (tabela `instancias`). Se ela voltar com outro celular, é
  desconectada na hora e abre o alerta "instância reconectada com outro
  celular". Outro número exige apagar e criar outra instância.
- Queda definitiva (`connection.update` com `close` ou `refused`) abre o
  alerta "instância desconectada", um por instância enquanto estiver aberto.
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
| `SATURDAY_EVOLUTION_WEBHOOK_URL` | Para onde a Evolution manda os eventos (padrão `http://api:8000/webhooks/evolution`) |
| `EVOLUTION_POSTGRES_SENHA` | Senha do Postgres próprio da Evolution |

Com o canal ligado e fora de `pytest`, faltar a chave ou o token derruba a
subida.

## Ligar num ambiente

1. Acrescente `evolution` em `COMPOSE_PROFILES`, preencha as variáveis acima,
   ligue `SATURDAY_EVOLUTION_ATIVO=true` e faça o deploy. Sobem `evolution`,
   `evolution-postgres` e `evolution-redis`, sem porta e sem domínio.
2. No painel, como gestor, abra **Canais**, crie a instância e leia o QR no
   celular (WhatsApp, Aparelhos conectados). O Saturday já configura o webhook
   (`MESSAGES_UPSERT`, `MESSAGES_UPDATE`, `CONNECTION_UPDATE`, com o token no
   header) e o `readMessages`.
3. Instância criada fora do painel (ou antes da tela existir): desconecte e
   clique **Reconectar**, que reaplica a configuração antes do QR.

## Desenvolvimento

O `compose.override.yaml` sobe `evolution-sim` na porta 8300 e aponta
`SATURDAY_EVOLUTION_URL` para ele. Para usar, ligue o canal com os valores
padrão do simulador (`chave-do-simulador`, `token-do-simulador`); a tela Canais
cria instâncias em memória nele.

```bash
curl -X POST localhost:8300/admin/mensagem -H 'content-type: application/json' \
  -d '{"texto": "Oi"}'
curl localhost:8300/admin/enviadas
curl -X POST localhost:8300/admin/falhas -d '{"status": 500}'   # ou {"inexistente": true}
curl -X POST localhost:8300/admin/conexao -H 'content-type: application/json' \
  -d '{"instancia": "mex-sim", "estado": "open", "telefone": "5511987654321"}'
```

## Riscos

- WhatsApp Web não é oficial: o número pode ser banido. Evite aviso proativo em
  excesso.
- Contato que chega só com `@lid` (sem telefone) é ignorado e fica no log.
