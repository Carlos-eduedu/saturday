# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Atendentes da MEX:** acompanham as conversas que o agente conduz no WhatsApp, assumem quando a IA passa a vez (handoff) ou quando veem algo errado, respondem e devolvem a conversa à IA.
- **Gestores da MEX:** fazem o mesmo que os atendentes e também cuidam dos canais (números da Meta e instâncias da Evolution), da cota da Granatech e dos alertas.
- **Onde usam:** desktop e celular, sem um predominar. Toda tela precisa funcionar bem nos dois.
- **Clientes finais:** pessoas que pedem crédito consignado. Falam só pelo WhatsApp e nunca veem o painel.

## Product Purpose

O Saturday é o agente de atendimento autônomo da MEX no WhatsApp. Ele conduz sozinho a jornada de crédito consignado: portabilidade INSS → C6 e Crédito do Trabalhador (CLT) pela Granatech, da triagem e do consentimento até a proposta, a biometria e o pagamento. O painel existe para a equipe acompanhar esse trabalho.

Sucesso do painel: a equipe **supervisiona a IA e intervém antes que um erro chegue ao cliente**. Responder handoffs e gerir canais são parte disso, mas o que desempata é enxergar a tempo o que a IA está fazendo e conseguir agir na hora.

## Positioning

As decisões que importam (triagem, consentimento, regras do banco, cálculos, teto de R$ 6.999, transições de estado) ficam em código determinístico e testado. O LLM só classifica intenção e responde dúvidas ancoradas na FAQ, e nunca escreve números, valores ou condições. Tudo o que o agente faz fica registrado, e a equipe pode assumir qualquer conversa.

## Operating Context

- **Estado de atendimento de cada conversa:** com a IA, em handoff (aguardando humano) ou assumida por um atendente, que vira dono dela. Enquanto está assumida, a IA fica calada. Os termos estão em `GLOSSARY.md`.
- **Canais:**
  - WhatsApp pela Cloud API da Meta, com janela de 24 h; fora dela, só modelos aprovados.
  - WhatsApp Web pela Evolution, sempre texto livre.
  - O mesmo celular em dois canais são duas conversas.
- **Tempo real:** o painel recebe os avisos por SSE (mensagens, mudanças de atendimento, alertas).
- **Alertas:** handoff novo, erro interno, envio que desistiu, cliente sem resposta, cota a 80%, consulta Granatech parada e instância da Evolution caída ou reconectada com outro celular.
- **Ficha do cliente:** dados mascarados. Revelar um dado fica gravado na auditoria.

## Capabilities and Constraints

- **Perfis:** atendente (conversas) e gestor (tudo, inclusive canais).
- **Login e sessão:** e-mail e senha (argon2id), bloqueio depois de 5 tentativas, sessão de 8 h, CSRF em toda ação, auditoria de toda ação.
- **Dados pessoais:** CPF, telefone, e-mail, nome da mãe e endereço aparecem mascarados por padrão.
- **Consentimento:** nenhuma consulta ou proposta sem o "SIM" do próprio cliente, com prova gravada. O painel não pode criar atalhos que contornem isso.
- **Idioma:** português do Brasil em toda a interface.
- **Contrato do repositório:** as regras inegociáveis estão no `AGENTS.md`, e as decisões registradas em `docs/decisoes/`.

## Brand Commitments

- **Identidade:** o Saturday é uma ferramenta interna com identidade própria e não segue a marca da MEX.
- **Nome:** "Saturday".

## Evidence on Hand

- **Painel atual:** `apps/painel/` (React + Vite + TypeScript), com Inbox, Conversa, Alertas e Canais.
- **Dados de teste:** os simuladores da Meta, da Evolution e da Granatech em `simuladores/` geram conversas e eventos de teste.
- **O que não existe e não deve ser inventado:** dados reais de volume, métricas de atendimento ou depoimentos.

## Product Principles

1. **Supervisão antes de tudo.** O painel mostra o que a IA está fazendo e onde ela pode errar, e deixa a equipe intervir sem atrito.
2. **Dois aparelhos, mesma capacidade.** Toda ação importante (assumir, responder, devolver, resolver alerta) funciona tão bem no celular quanto no desktop.
3. **Dados pessoais protegidos por padrão.** Mascarar é a regra, e revelar é exceção auditada.
4. **A interface não decide pelo código.** O painel nunca toma decisões que o contrato reserva ao código determinístico (consentimento, valores, propostas).
