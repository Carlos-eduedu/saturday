# 0026 — Contrato novo e refinanciamento INSS no C6, pela API do banco

- **Data:** 2026-11-16
- **Status:** aceita
- **Desvia de:** `AGENTS.md`, regra 1 (lista de parceiros) e "Fora do escopo"

## Contexto

O ramo INSS só calcula a portabilidade para o C6 pelo extrato e passa a
conversa para o atendente digitar. O Saturday não fala com o C6.

A operação quer que o agente também venda contrato novo (margem livre) e
refinanciamento de contrato que o cliente já tem no C6. O C6 tem uma API
oficial para esses dois produtos (Manual API V30, 26/01/2026): simulação,
inclusão de proposta, consulta e link de formalização. A portabilidade não
passa por essa API e continua como está.

## Decisão

- O C6 entra na lista de parceiros externos da regra 1. O Saturday chama a API
  do C6 direto, com credencial própria; nunca pelo hub `mex-c6-api`, que é
  sistema da MEX.
- Contrato novo e refinanciamento INSS no C6 entram no escopo. C6 CLT, FGTS e
  os demais bancos continuam fora.
- O agente simula, oferece e digita a proposta pela API, como no CLT. A regra 4
  vale igual: sem repetição automática da inclusão, intenção gravada antes.
- Nenhuma simulação no C6 sem o "SIM" do cliente com prova gravada (regra 3).
- Ordem de oferta: contrato novo, refinanciamento de contrato do C6,
  portabilidade.
- Entre as condições que a simulação devolve, o agente oferece a da faixa de
  maior taxa até 1,85% ao mês e, dentro dela, a de maior valor na conta do
  cliente. É a política que a operação já usa.
- Os dados do cliente vêm do extrato de empréstimos e do que ele informa na
  conversa. O Promosys é sistema da MEX e não é consultado.
- O cliente da API é escrito a partir do manual do C6 (regra 12), com simulador
  para os testes (regra 11).

## Pendências

- `TODO(c6): credencial própria do Saturday na API` (pedida ao C6).
- `TODO(c6): Manual API V30` (a operação envia). Sem ele não há cliente.
- `TODO(c6): de onde vem a renda do benefício, que a simulação exige?` O extrato
  lido hoje não a guarda.
- O extrato lido hoje não guarda o número do benefício nem o número de cada
  contrato, que a simulação do refinanciamento exige.

## Alternativas descartadas

- **Usar o hub da MEX.** Quebra a regra 1.
- **Dividir a credencial do CRM.** O C6 limita cerca de uma chamada por segundo
  por credencial; o Saturday disputaria o limite com o CRM e a Deu Plim.
- **Atendente digita.** Mantém o trabalho manual que a mudança quer tirar.
- **Robô no portal do C6 para a portabilidade.** Caro e frágil; fora desta
  decisão.
