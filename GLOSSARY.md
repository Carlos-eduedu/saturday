# Saturday

Agente de atendimento autônomo da MEX no WhatsApp, com um painel para a equipe
acompanhar e assumir conversas.

## Atendimento

**Canal**:
Por onde a conversa entra e sai: a Cloud API da Meta (`whatsapp`), a Evolution
(`evolution`) ou o contrato HTTP (`chat`). Uma conversa pertence a um canal só;
o mesmo celular em dois canais são duas conversas.
_Evitar_: provedor, integração

**Janela**:
As 24 h desde a última mensagem do cliente em que a Meta aceita texto livre;
fora dela, só modelo. Só existe no canal `whatsapp`.
_Evitar_: sessão

**Estado de atendimento**:
Quem responde a conversa naquele momento: a IA, ninguém (handoff) ou um
atendente (assumida).
_Evitar_: status da conversa (no código, `status` também é o resultado do turno)

**Handoff**:
Estado em que a IA desistiu de responder e a conversa espera um humano, sem dono.
_Evitar_: aguardando humano, escalada

**Conversa assumida**:
Estado em que um atendente específico é o dono da conversa; a IA fica calada.
_Evitar_: com humano, em atendimento

**Assumir**:
Um atendente tornar-se dono de uma conversa, venha ela da IA ou de um handoff.

**Devolver**:
Tirar a conversa de handoff ou de assumida e entregá-la de volta à IA.
_Evitar_: liberar, release

**Transferir**:
Trocar o dono de uma conversa assumida por outro atendente.

**Autor**:
Quem escreveu uma mensagem de saída: a IA, um atendente ou o sistema (modelo).

**Alerta**:
Algo que pede atenção da equipe: handoff novo, erro interno, envio que desistiu
ou cliente sem resposta numa conversa assumida.

**Ficha**:
Os dados pessoais e de jornada de um cliente, mostrados mascarados no painel.

**Revelar**:
Mostrar ao usuário do painel um dado pessoal sem máscara; sempre deixa rastro
na auditoria.
_Evitar_: desmascarar, ver completo

## Crédito do Trabalhador

**Consulta**:
Pedido à Granatech para ver o emprego, o salário e a margem de um CPF; cada
uma gasta cota.
_Evitar_: consulta de saldo (fora da borda com a API), pesquisa

**Cota**:
Quantas consultas a MEX pode abrir na Granatech, por dia e por mês.

**Reaproveitamento**:
Usar uma consulta recente do mesmo CPF em vez de abrir outra.

**Vínculo**:
Um emprego do cliente que tem margem, com seus produtos de crédito.
_Evitar_: margem (para o emprego), matrícula

**Simulação**:
Cálculo de uma condição de crédito para um vínculo; não gasta cota.

**Liberado**:
O valor que cai na conta do cliente, sem IOF nem seguro.
_Evitar_: valor solicitado (fora da borda com a API), valor do empréstimo

**Teto**:
O maior liberado que a MEX apresenta ou contrata (R$ 6.999).

**Triagem**:
Perguntas ao cliente, antes de qualquer consulta, que descartam quem não pode
contratar; não gasta cota.
_Evitar_: pré-análise, qualificação

**Oferta**:
A condição de crédito simulada que o agente apresenta ao cliente, sempre
dentro do teto e com o seguro dito por extenso.
_Evitar_: proposta (proposta é o que se cria no banco depois do aceite)

**Aceite**:
O SIM do cliente ao resumo fechado da oferta, com os valores e a conta; é o que
autoriza criar a proposta.
_Evitar_: contratação, fechamento

**Proposta**:
O pedido de crédito criado no banco depois do aceite; acompanha a
formalização até o pagamento.
_Evitar_: oferta (oferta é a condição apresentada antes do aceite), contrato

**Formalização**:
A etapa em que o cliente confirma a identidade no banco (biometria) pelo link
que o agente envia.
_Evitar_: assinatura, validação

**Não elegível**:
Fim da jornada para quem a triagem, a empresa, a idade ou a consulta
reprovaram; só um atendente reabre.
_Evitar_: reprovado (reprovado é status de proposta no banco)

**Recontato**:
Voltar a falar com o cliente numa data marcada, porque algo o impediu de seguir
agora (tempo de casa curto, cota esgotada).
_Evitar_: follow-up, retorno

## Equipe

**Atendente**:
Usuário do painel que atende conversas.

**Gestor**:
Usuário do painel com acesso a tudo, inclusive configuração e usuários.
_Evitar_: admin, supervisor
