# Saturday

Agente de atendimento autônomo da MEX no WhatsApp, com um painel para a equipe
acompanhar e assumir conversas.

## Atendimento

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

## Equipe

**Atendente**:
Usuário do painel que atende conversas.

**Gestor**:
Usuário do painel com acesso a tudo, inclusive configuração e usuários.
_Evitar_: admin, supervisor
