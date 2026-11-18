# 0032 — Qualidade e número exibido lidos na Graph

- **Data:** 2026-11-18
- **Status:** aceita
- **Complementa:** [decisão 0019](0019-barra-nova-membros-operacao-e-canal-ativo.md)

## Contexto

A seção da Meta na tela Canais mostrava só o `phone_number_id`. A 0019 deixou a
qualidade, o número exibido e a gestão dos números para depois, por causa das
regras 8 (token no banco) e 12 (rota fora da especificação). Na issue 31 o dono
decidiu (2026-11-18): entra só a leitura melhorada.

## Decisão

- A tela Canais mostra, para cada número da Meta, o **número exibido**
  (mascarado, como o telefone das instâncias da Evolution) e a **qualidade**.
- **Criar, editar e excluir número continua fora do painel.** A regra 8 não
  muda: o token da Meta segue só em `SATURDAY_WHATSAPP_TOKEN`.
- **Desvio da especificação (regra 12):** a seção "Especificação: WhatsApp e
  painel" não descreve esta leitura. O contrato usado, conferido na
  documentação oficial da Meta em 2026-11-18:
  - Rota: `GET {SATURDAY_WHATSAPP_GRAPH_URL}/{phone_number_id}`, com
    `Authorization: Bearer <token>`, sem o parâmetro `fields`.
  - Campos lidos da resposta: `display_phone_number` (texto) e
    `quality_rating`. A resposta padrão traz também `id` e `verified_name`,
    que o Saturday não usa.
  - Valores de `quality_rating` na referência: `GREEN` (alta), `YELLOW`
    (média), `RED` (baixa) e `NA` (ainda não determinada). O guia traz também
    `UNKNOWN` num exemplo de listagem, sem explicar: valor fora da lista
    aparece cru na tela.
  - Páginas consultadas:
    <https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/whatsapp-business-account-phone-number-api>
    (referência: rota, campos e valores) e
    <https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers>
    (guia "Business phone numbers": exemplo de requisição e resposta).
- **Sem chamar a Meta a cada abertura:** a API guarda cada leitura na memória do
  processo por 60 s, com ou sem sucesso, já com o telefone mascarado. Sem
  tabela nova e sem variável de ambiente nova.
- **Falha não derruba a tela:** se a Meta recusa ou não responde em 5 s, a
  linha do número mostra "Não foi possível consultar a Meta" e o
  `phone_number_id`. Sem retry: a próxima abertura depois da validade consulta
  de novo.
- O log da leitura guarda só status e código do erro; o número exibido nunca
  vai para o log.

## Alternativas descartadas

- **Guardar a leitura no banco**, como o telefone fixado das instâncias (0010):
  lá o dado guardado sustenta uma regra (bloquear troca de telefone); aqui é só
  exibição.
- **Mostrar o número inteiro, ou com "revelar" auditado:** a Evolution já mostra
  o telefone do canal mascarado, e a tela segue igual.
- **Pedir `fields=`** para trazer `name_status` ou `code_verification_status`:
  ninguém pediu.

## Consequências

- O simulador da Meta responde `GET /{phone_number_id}` com os mesmos campos, e
  `POST /admin/numero` troca a qualidade.
- Com mais de um processo da API, cada um tem a sua memória: a Meta recebe, no
  máximo, uma leitura por número por minuto por processo.
