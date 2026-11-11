# Webhook de propostas (Granatech)

Transcrição do PDF "GRANATECH3-Propostas" enviado pela Granatech (o PDF fica
fora do git, como todo `*.pdf`).

Toda notificação de proposta tem esta forma:

```json
{
  "tipo": "proposta",
  "status_da_proposta": "PENDING_CONFIRMATION",
  "tipo_notificacao": "AGUARDANDO_CONFIRMACAO",
  "id_proposta": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "informacoes": "Proposta criada com sucesso na plataforma"
}
```

## Combinações documentadas

| `status_da_proposta` | `tipo_notificacao` | `informacoes` (exemplo) |
| --- | --- | --- |
| `PENDING_CONFIRMATION` | `AGUARDANDO_CONFIRMACAO` | Proposta criada com sucesso na plataforma |
| `PENDING_USER_REVIEW` | `AGUARDANDO_REVISAO_USUARIO` | Existem pendências na criação da proposta |
| `PENDING_USER_REVIEW` | `FALHA_PAGAMENTO` | Aguardando revisão de dados bancários pelo usuário |
| `PENDING_FORMALIZATION` | `AGUARDANDO_FORMALIZACAO` | Proposta criada com sucesso no banco e segurança da identidade |
| `PENDING_FORMALIZATION` | `FORMALIZACAO_EM_ANDAMENTO` | Bloqueio de saldo realizado, aguardando formalização |
| `PENDING_FORMALIZATION` | `BLOQUEIO_DE_SALDO_EM_ANDAMENTO` | Bloqueio de saldo em andamento |
| `PENDING_FORMALIZATION` | `BLOQUEIO_SALDO` | Bloqueio de saldo realizado, pagamento em andamento |
| `PENDING_REFORMALIZATION` | `REFAZER_SEGURANCA_IDENTIDADE` | Usuário precisa refazer processo de Segurança de identidade |
| `PENDING_BANK_ANALYSIS` | `AGUARDANDO_ANALISE_BANCO` | Aguardando análise do banco sobre a segurança de identidade |
| `PENDING_PAYMENT` | `SUCESSO_SEGURANCA_IDENTIDADE` | Segurança de identidade aprovada com sucesso |
| `REPROVED` | `REPROVADO` | Segurança de identidade reprovada |
| `CANCELED` | `PROPOSTA_CANCELADA` | Proposta cancelada no banco; ou o motivo, por exemplo "O saldo disponível não é suficiente para a garantia requerida", "O valor indicado não está disponível para a contratação", "Protocolo removido na CEF" |
| `CANCELED` | `BLOQUEIO_DE_SALDO_CANCELADO` | Proposta cancelada |
| `PAYED` | `PAGO` | Proposta paga |
| `PAYED` | `PROPOSTA_PAGA` | Proposta paga |

O documento também cita duas notificações sem exemplo: "consulta-saldo pronta"
(a consulta de saldo na CEF foi realizada) e "criação de proposta e processo nos
terceiros finalizada".

No Saturday, cada combinação vira uma ação em
`bancos/granatech/status.py::acao_da_proposta`; `CANCELED` com qualquer
notificação encerra a jornada.
