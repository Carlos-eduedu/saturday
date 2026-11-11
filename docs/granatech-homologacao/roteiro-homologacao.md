Etapas e mensagens de envio aos consumidores da API

O primeiro texto é uma apresentação do que oferecemos e os principais aspectos da parceria, do processo de desenvolvimento e acompanhamento até a operação no mundo real:
---

# API Granatech

A **API Granatech** permite a integração sistêmica com nossas esteiras de crédito, abrangendo desde a consulta e simulação até a contratação e o acompanhamento de propostas.

## 🚀 Ambientes
Disponibilizamos dois ambientes distintos para garantir a segurança e a integridade da sua operação:

* **Sandbox (HML):** Destinado a testes, validações e implementações. Os dados são fictícios e as operações não geram efeitos financeiros reais.
* **Produção (PRD):** Ambiente real para operações oficiais após a conclusão da fase de homologação.

---

## 🛠 Processo de Homologação

O processo é dividido em etapas fundamentais para garantir que a integração esteja robusta antes do Go-Live.

### 1. Cadastro e Setup Inicial
O fluxo inicia com o alinhamento comercial. Após a aprovação, seu perfil será criado no ambiente de desenvolvimento.
* **Apoio:** Você receberá um arquivo **Postman** pré-configurado e o acesso ao **Swagger**.
* **Webhook:** É necessário definir a rota (URL) que receberá as notificações de callback.

### 2. Fase de Consultas e Simulações
Nesta etapa, validamos a comunicação básica. Para avançar, é necessário entregar:
* **2 Evidências de Consulta:** (via requisição direta e via notificação de Webhook).
* **2 Simulações:** (com e sem seguro).

### 3. Fase de Contratação e Pós-Venda
Validação do fluxo crítico da operação. Requisitos para publicação em PRD:
* **2 Evidências de Contratação com Sucesso:** (via requisição direta e Webhook).
* **1 Evidência de Erro de Contratação:** (para validar o tratamento de exceções).

---

## 🔐 Acessos e Autenticação

Os domínios base para as requisições são:
* **HML:** `https://api-dev.granatech.com.br/`
* **PRD:** `https://api.granatech.com.br/`

### Fluxo de Autenticação
A autenticação utiliza o método **Bearer Token**. Primeiro, obtenha seu token de acesso:

```bash
curl --location '{URL_AMBIENTE}/api/v1/auth/login' \
--header 'Content-Type: application/json' \
--data '{
    "chave_api": "SUA_CHAVE_AQUI"
}'
```

> [!IMPORTANT]
> O retorno conterá o objeto `token` e o campo `expira_em`. Utilize este token no header `Authorization` de todas as chamadas subsequentes.

---

## 🔔 Notificações (Webhooks)

Nossa arquitetura é orientada a eventos. Recomendamos priorizar o consumo das notificações enviadas pelo nosso sistema em vez de realizar *polling* (consultas repetitivas de status).

* **Eventos cobertos:** Alterações no status da consulta, etapas da contratação e confirmação de pagamento.
* **Segurança:** É altamente recomendável (embora opcional) o uso de **secrets/credenciais** na rota de recebimento das notificações para garantir a autenticidade da origem.

---

## 📈 Produção e Suporte

Após a homologação e o recebimento das credenciais definitivas, você contará com:
* **Suporte Técnico:** Auxílio em dúvidas de integração.
* **Apoio Operacional:** Suporte ao negócio e fluxo de propostas.
* **Dashboard:** Acompanhamento via interface web em [www.granatech.com.br](https://www.granatech.com.br).

---

## Consumo e Volumetria

O consumo de informações via API é restrito por volumetrias e planos como segue:

### Consignado trabalhador
| Nível | Nº Consultas | Nº Consultas Sucesso | Nº de CCBS | % Consulta/CCB | Consultas/CCB | Custo Total | Custo por CCB |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 1.000 | 200 | 200 | 20,0% | 5,0 | R$ 200,00 | R$ 1,00 |
| 1 | 5.000 | 900 | 900 | 18,0% | 6,0 | R$ 1.000,00 | R$ 1,11 |
| 2 | 10.000 | 1.600 | 1.600 | 16,0% | 7,0 | R$ 2.000,00 | R$ 1,25 |
| 3 | 25.000 | 3.750 | 3.750 | 15,0% | 8,0 | R$ 5.000,00 | R$ 1,33 |
| 4 | 50.000 | 7.000 | 7.000 | 14,0% | 7,1 | R$ 10.000,00 | R$ 1,43 |
| 5 | 100.000 | 13.000 | 13.000 | 13,0% | 12,0 | R$ 20.000,00 | R$ 1,54 |

### FGTS
| Nível | Nº Consultas | Nº de CCBS | % Consulta/CCB | Consultas/CCB | Custo Total | Custo por CCB |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 1.000 | 200 | 20,0% | 5,0 | R$ 200,00 | R$ 1,00 |
| 1 | 5.000 | 900 | 18,0% | 6,0 | R$ 1.000,00 | R$ 1,11 |
| 2 | 10.000 | 1.600 | 16,0% | 7,0 | R$ 2.000,00 | R$ 1,25 |
| 3 | 25.000 | 3.750 | 15,0% | 8,0 | R$ 5.000,00 | R$ 1,33 |
| 4 | 50.000 | 7.000 | 14,0% | 7,1 | R$ 10.000,00 | R$ 1,43 |
| 5 | 100.000 | 13.000 | 13,0% | 12,0 | R$ 20.000,00 | R$ 1,54 |

---

# Mensagens das etapas de imlantação para Consignado e FGTS:
os processos são iguais e devemos enviar as documentações e informações referentes a cada produto
lista de documentos disponíveis:
    >postman para fase de consulta e simulação 
    >postman para fase de contatação
    >documentação de webhoks de consultas 
    >documentação de webhoks de propostas
    >documentação de status e mensagens 
    >swagger >> entregue apenas após a validação da consulta e simulação [https://api-dev.granatech.com.br/doc#]


---

### 📩 Etapa 0: Boas-vindas e Setup Inicial
**Foco:** Entrega das credenciais no postman (consulta e sumulação) e documentação dos Webhooks.

> **Assunto:** Bem-vindo à API Granatech | Materiais para Homologação 🚀
>
> Olá! Seu perfil no ambiente de desenvolvimento já está ativo.
>
> Para iniciarmos a integração, seguem os materiais necessários:
> * **URL de HML:** `https://api-dev.granatech.com.br/`
> * **Collection Postman:** (Anexo) Já configurada com rotas e variáveis.
> * **📘 Documentação do Webhook (Fase 1):** Segue o esquema de retorno para os eventos de **consulta**.
>
> **Próximo passo:** Realize a autenticação utilizando sua `chave_api` e nos informe a URL do seu Webhook para configurarmos as notificações.

---

### 📩 Etapa 1: Validação de Consultas e Simulações
**Foco:** Reforçar a validação do retorno do Webhook para os primeiros disparos.

> **Assunto:** Homologação Granatech | Fase 1: Consultas e Simulações
>
> Sua rota de notificações já está cadastrada!
>
> Por favor, nos envie os logs ou prints de:
> 1. **2 Evidências de Consulta:** (Uma via resposta direta e outra via notificação do Webhook).
> 2. **2 Simulações:** (Uma com seguro e outra sem seguro).

---

### 📩 Etapa 2: Validação de Contratação e Erros
**Foco:** Entrega do mapeamento de postman com rotas de contatação e documentação de notificações, etc.

> **Assunto:** Homologação Granatech | Fase 2: Fluxo de Contratação
>
> Recebemos as evidências da Fase 1 e está tudo certo! Agora, vamos para o fluxo crítico de contratação.
>
>
> Nesta fase, precisamos de:
> * **2 Evidências de Contratação com Sucesso** (Validando a recepção do status via Webhook).
> * **1 Evidência de Erro de Contratação** (Para garantirmos que seu sistema trata as mensagens de erro e notificações de falha).

---

### 📩 Etapa 3: Liberação de Produção (Go-Live)
**Foco:** Consolidação e entrega das credenciais reais.

> **Assunto:** 🚀 Homologação Concluída! Suas credenciais de Produção chegaram.
>
> Parabéns! Sua integração com a API Granatech foi homologada com sucesso.
>
> **Dados de Produção:**
> * **URL:** `https://api.granatech.com.br/`
> * **Chave de Produção:** [Sua Chave Aqui]
>
> Lembre-se: em Produção, as operações são reais. Continuamos à disposição para suporte técnico e apoio operacional através do [Link do Suporte].

---









