# 0007 — Triagem antes da identificação no ramo CLT

- **Data:** 2026-11-11
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, "Especificação: jornada CLT" (ordem das etapas)

## Contexto

O `AGENTS.md` ordena as etapas como `abertura` → `identificacao` → `triagem` →
`empresa` → `consentimento`. Assim o agente pede CPF, nome, nascimento e sexo
antes de saber se o cliente tem carteira assinada, 12 meses de casa e empresa
elegível.

## Decisão

A ordem passa a ser `abertura` → `triagem` → `empresa` → `identificacao` →
`consentimento`. A conferência de idade × prazo continua logo depois de
nascimento e sexo, dentro da identificação. Nenhuma etapa deixa de existir e
nenhuma regra muda; só a ordem.

## Por quê

- Minimização de dados pessoais: não se guarda CPF de quem a triagem reprova.
- Menos atrito: o cliente responde perguntas de sim/não antes de dar documento.
- Nada da triagem nem da empresa depende do CPF.

## Alternativas descartadas

- **Manter a ordem do contrato.** Coleta dado pessoal sem necessidade e põe a
  parte mais trabalhosa da conversa antes da mais barata.
