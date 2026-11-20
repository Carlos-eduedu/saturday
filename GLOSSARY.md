# Saturday

Agente de atendimento autônomo da MEX no WhatsApp, com um painel para a equipe
acompanhar e assumir conversas.

## Atendimento

**Canal**:
Por onde a conversa entra e sai: a Cloud API da Meta (`whatsapp`), a Evolution
(`evolution`) ou o contrato HTTP (`chat`). Uma conversa pertence a um canal só;
o mesmo celular em dois canais são duas conversas.
_Evitar_: provedor, integração

**Instância**:
Um número de WhatsApp conectado à Evolution pelo QR. O Saturday atende toda
instância da sua própria Evolution; o gestor cria, reconecta, desconecta e
apaga instâncias na tela Canais.
_Evitar_: conexão, sessão, número (para a instância)

**Janela**:
As 24 h desde a última mensagem do cliente em que a Meta aceita texto livre;
fora dela, só modelo. Só existe no canal `whatsapp`.
_Evitar_: sessão

**Turno**:
Uma rodada do grafo para uma conversa, com a resposta que ela produz.
_Evitar_: execução, rodada (rodada é da homologação)

**Turno de sistema**:
Turno sem mensagem do cliente, disparado por um evento do banco, por um
recontato ou pelo gestor.

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

**Membro**:
Pessoa da equipe com acesso ao painel: atendente ou gestor.

**Função**:
O que o membro faz na equipe (ex.: "Atendente CLT"), em texto livre do gestor.
Não muda o que a pessoa pode fazer: isso é do perfil.

**Estado do membro**:
Disponível (usou o painel há menos de 5 min), ausente (a própria pessoa marcou)
ou fora do painel. Informa quem transfere; não bloqueia.

**Autor**:
Quem escreveu uma mensagem de saída: a IA, um atendente ou o sistema (modelo).

**Alerta**:
Algo que pede atenção da equipe: handoff novo, erro interno, envio que desistiu,
atendente desativado com conversas ou cliente sem resposta numa conversa assumida.

**Ficha**:
Os dados pessoais e de jornada de um cliente, mostrados mascarados no painel.

**Resposta rápida**:
Texto salvo que o atendente insere na conversa digitando "/" e o atalho; quem
envia revisa antes. Não passa pela IA.
_Evitar_: template, modelo (modelo é a mensagem aprovada na Meta)

**Revelar**:
Mostrar ao usuário do painel um dado pessoal sem máscara; sempre deixa rastro
na auditoria.
_Evitar_: desmascarar, ver completo

## Crédito do Trabalhador

**Consulta**:
Pedido a um banco para ver o que ele oferece a um CPF. Na Granatech mostra o
emprego, o salário e a margem e gasta cota; no iCred já devolve as condições de
crédito.
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
dentro do teto e com o seguro dito por extenso. No iCred, a oferta é o pacote:
todos os contratos que o banco devolve para o CPF, aceitos juntos.
_Evitar_: proposta (proposta é o que se cria no banco depois do aceite)

**Aceite**:
O SIM do cliente ao resumo fechado da oferta, com os valores e a conta; é o que
autoriza criar a proposta.
_Evitar_: contratação, fechamento

**Proposta**:
O pedido de crédito criado no banco depois do aceite; acompanha a
formalização até o pagamento.
_Evitar_: oferta (oferta é a condição apresentada antes do aceite), contrato,
gravação (gravar é o nome da operação na borda com o iCred)

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

**Reconciliar**:
Procurar no banco uma proposta cujo envio teve resultado incerto, antes de
qualquer nova tentativa; nunca cria outra proposta.
_Evitar_: reenviar, tentar de novo

**Homologação**:
O processo em que a Granatech valida a integração da MEX, em duas fases
(consultas e simulações; contratação), antes de liberar a produção.
_Evitar_: homolog (homolog é o ambiente do Saturday, não o processo)

**Rodada**:
Uma execução de uma fase da homologação, disparada pelo gestor.
_Evitar_: teste, execução

**Evidência**:
O registro de uma chamada à Granatech ou de um webhook recebido que prova um
item do roteiro da homologação.
_Evitar_: log, print

## Equipe

**Atendente**:
Usuário do painel que atende conversas.

**Gestor**:
Usuário do painel com acesso a tudo, inclusive configuração e usuários.
_Evitar_: admin, supervisor

## Integração

**APP MEX**:
Sistema da MEX que usa o Saturday para falar com a Granatech. Colhe a triagem e
o consentimento do cliente por conta própria.

**Integração**:
Acesso de um sistema de fora ao Saturday, com token, escopos e o endereço que
recebe os avisos. Não é um canal: por ela não passa conversa com o cliente.
_Evitar_: canal, provedor

**Parceiro**:
Serviço externo que o Saturday chama: Meta, Evolution, Granatech, C6, iCred,
BrasilAPI, OpenRouter, a transcrição de áudio e o storage. O oposto da
integração: é o Saturday quem chama, não quem é chamado. A chave de um parceiro
nunca é editada pelo painel.
_Evitar_: integração, provedor, fornecedor

**Proxy**:
O papel do Saturday na integração: repassa à Granatech o pedido no formato dela
e só barra o que fura a cota, o teto ou o escopo.
_Evitar_: balcão manual (o que a decisão 0013 recusou)
