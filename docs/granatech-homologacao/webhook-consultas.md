# Webhook de consultas (Granatech)

Transcrição do PDF "Consultas-Webhook" enviado pela Granatech. O CPF e o
`user_id` do exemplo foram trocados pelos dados de teste; o PDF original fica
só na máquina de quem o recebeu (está no `.gitignore`).

O webhook da rota de consulta envia notificações sobre o status da solicitação
de consulta de saldo.

## Exemplo de notificação

```json
{
  "id_solicitacao": "a7e3587e-cd73-4998-bae3-ec000ab6bb6b",
  "id_proposta": "6fdf2acb-cd75-416f-8754-3744e786a6a6",
  "cpf": "00189004967",
  "status": "AWAITING_CLIENT_AUTHORIZATION",
  "user_id": "00000000000.38",
  "corban_id": 38,
  "tipo": "CONSULTA"
}
```

## Estrutura

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `id_solicitacao` | string | Identificador único da solicitação de consulta |
| `id_proposta` | string | ID da proposta associada |
| `cpf` | string | CPF do cliente relacionado à solicitação |
| `status` | string | Status atual da solicitação |
| `user_id` | string | Identificador do usuário na plataforma |
| `corban_id` | number | Identificador interno do banco/entidade |
| `tipo` | string | Tipo de solicitação (`CONSULTA`) |

## Status possíveis

- `AWAITING_CLIENT_AUTHORIZATION`: aguardando autorização do cliente (rota de
  assinatura do termo de consentimento).
- `PROCESSING`: em processamento.
- `SUCCESS`: concluída com sucesso.
- `PENDING`: pendente.
- `NO_MARGIN`: cliente sem margem disponível.
- `USED`: solicitação já utilizada.
- `UNEXPECTED_ERROR`: erro inesperado no processamento.
