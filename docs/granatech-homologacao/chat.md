# Exportação de conversas do WhatsApp: API Mex X GranaTech
Data de exportação: 11 de novembro de 2026 às 18:35

---

## 28 de outubro de 2026

[13:59] __As mensagens e as ligações são protegidas com a criptografia de ponta a ponta e ficam somente entre você e os participantes desta conversa. Nem mesmo o WhatsApp pode lê-las ou ouvi-las. Toque para saber mais.__

[13:59] __*[MEX] criou o grupo__

[14:04] __[MEX] adicionou Você__

[14:04] **[MEX]:** Boa tarde, equipe Mex no grupo

[14:06] ***[MEX]:** Boa tarde pessoal. @[Granatech] vai passar aqui as fases para início da integração assim que possível .

[14:07] **Você:** Boa tarde

[14:47] **[Granatech]:** Olá, pessoal. Boa tarde, tudo bem?

[14:47] **[Granatech]:** Vamos ajustar o ambiente de HML de vocês e liberar aqui a documentação para vocês darem sequência nas interações.

Lembrando que as interações com nossa API precisam efetuar alguns testes em HML para liberarmos as chaves em PRD.

[14:47] **[Granatech]:** Preciso da URL do webhook hml, onde vamos mandar atualizações dos status das consultas e propostas para homologação.

Podem me enviar aqui?

[14:48] __[Granatech] mudou o nome do grupo para "API Mex X GranaTech"__

---

## 29 de outubro de 2026

[9:31] **Você:** Olá bom dia a todos

[9:33] **Você:**
> _[Granatech]: Preciso da URL do webhook hml, onde vamos mandar atualizações dos status das consultas e propostas para homologação.

Podem me enviar aqui?_
Consegue me enviar os schemas que serão enviados ao webhook?

---

## 30 de outubro de 2026

[8:23] **[Granatech]:** Bom dia, pessoal!

[8:23] **[Granatech]:** Sim, vou mandar a documentação, mas preciso da URL em HML para enviar essas credenciais

[8:23] **[Granatech]:** [Documento] API_ROTEIRO.md

[8:23] **[Granatech]:** [Documento] Consultas-Webhook (1).pdf

[8:23] **[Granatech]:** [Documento] GRANATECH3-Propostas-050326-173127 (1).pdf

[8:23] **[Granatech]:** https://api-dev.granatech.com.br/doc#/

---

## 3 de novembro de 2026

[13:56] ***[MEX]:** Boa tarde @[MEX] tudo bem?

[13:56] ***[MEX]:** Como está a integração?

[14:34] **Você:** Opa, boa tarde! Tô quase finalizando. Tivemos um pequeno contratempo, mas acredito que amanhã cedo já consigo enviar o endpoint do webhook

---

## 4 de novembro de 2026

[15:52] **Você:** Olá, boa tarde! O webhook está disponível neste endereço: https://granatech.dynatech.systems/webhooks/granatech

[16:45] **[Granatech]:** Show, vamos providenciar o ambiente em HML e mando as etapas aqui pra concluirmos a homologação!

---

## 9 de novembro de 2026

[12:13] ***[MEX]:** Boa tarde

[12:13] ***[MEX]:** @[Granatech] como tá o andamento aqui ?

[13:38] **[Granatech]:** Boa tarde! Já vou mandar aqui

[14:03] **[Granatech]:** Homologação Granatech | Fase 1: Consultas e Simulações

Sua rota de notificações já está cadastrada!

Por favor, nos envie os logs ou prints de:
2 Evidências de Consulta: (Uma via resposta direta e outra via notificação do Webhook).
2 Simulações: (Uma com seguro e outra sem seguro).
API_KEY=[removida]
Documentacao das rotas de consultas e propostas:https://api-dev.granatech.com.br/doc#/

[14:03] **[Granatech]:** [Documento] Rotas consumo API-Granatech-CONSULTAS DEV CORBAN MEX.postman_collection.json

---

## 10 de novembro de 2026

[11:04] ***[MEX]:** [Encaminhada] API / homologação Fase 1
4. Simulação sem seguro: na dev, mesmo enviando seguro=false, a API devolve só resultado_da_simulacao_com_seguro, e a consulta de teste só traz produtos com seguro. Qual parâmetro desliga o seguro, ou podem habilitar o produto "sem_seguro" no nosso corban na dev?
5. A rota de notificações (webhook) cadastrada para nós: qual é a URL? Vocês mandam algum cabeçalho de segurança? Podemos trocar a rota por uma nova?
6. Em produção, o termo de consentimento assinado pela API (POST termo-consentimento) basta, ou o cliente precisa abrir o link de autorização?
7. Listar consultas: o filtro é "filterBy" (Swagger) ou "filtrar_por" (Postman)?
8. Na ida para produção, qual é a URL da API e como recebemos a chave de produção?

Fase 2 (propostas)
9. Em informacoesFinanceira, o que significa o campo tipo_empregador (número)? Quais valores existem?
10. Em informacaoDeSeguros, o id_externo é número no Swagger, mas a simulação devolve "SM-100000721-6". Mandamos como veio?
11. O PATCH /propostas/{id}/dados-bancarios está com corpo vazio no Swagger. É o mesmo banco_detalhe do dados-tomador?

Obrigado!

[11:04] ***[MEX]:** @[Granatech] qdo puder dá uma atenção nisso

[11:13] **Você:** Bom dia, @[Granatech] posso te enviar as evidencias de homologação por aqui mesmo?

[11:16] ***[MEX]:** Pode tratar tudo aqui [MEX]

[12:48] **Você:** {
    "atualizado_em": "2026-11-10T16:47:28.671Z",
    "criado_em": "2026-11-10T16:47:28.671Z",
    "cpf": "00189004967",
    "id": "4738ca0d-e81e-470d-8075-ceb0bc5de2d0",
    "id_corban": 399,
    "id_externo": null,
    "id_usuario": "[cpf removido].399",
    "nome": null,
    "link_termo_consentimento": "https://app-dev.granatech.com.br/consignado/autorizar-consulta?balanceSolicitationId=4738ca0d-e81e-470d-8075-ceb0bc5de2d0?balanceSolicitationId=4738ca0d-e81e-470d-8075-ceb0bc5de2d0",
    "origem": "SYSTEM",
    "status": "AWAITING_CLIENT_AUTHORIZATION",
    "telefone": null
}

[12:48] **Você:** Retorno via postman

[12:48] **Você:** 2026-11-10 16:47:29,278 INFO request_id=3eadea1e589246fe logger=granatech_webhook.web.application requisição recebida metodo=POST rota=/webhooks/granatech ip=20.206.208.98 content_length=137
2026-11-10 16:47:29,582 INFO request_id=3eadea1e589246fe logger=granatech_webhook.web.api.webhooks.service payload validado tipo=consulta id=4738ca0d-e81e-470d-8075-ceb0bc5de2d0 status=AGUARDANDO_AUTORIZACAO_DO_CLIENTE
2026-11-10 16:47:30,847 INFO request_id=3eadea1e589246fe logger=granatech_webhook.web.api.webhooks.service evento bruto gravado evento_id=9 rota=/webhooks/granatech duplicado=não
2026-11-10 16:47:30,897 INFO request_id=3eadea1e589246fe logger=granatech_webhook.web.api.webhooks.service evento tipo=consulta id=4738ca0d-e81e-470d-8075-ceb0bc5de2d0 status=AGUARDANDO_AUTORIZACAO_DO_CLIENTE tipo_notificacao=- evento_id=9 duplicado=não
2026-11-10 16:47:30,914 INFO request_id=3eadea1e589246fe logger=granatech_webhook.web.application resposta status=200 duracao_ms=1645.9 metodo=POST rota=/webhooks/granatech

[12:48] **Você:** Logs recebidos via webhook

[12:51] **Você:** _Mensagem apagada_

[12:55] ***[MEX]:** @[MEX] coloca teu pai aqui por favor

[12:55] __Você adicionou [MEX]__

[12:55] **Você:** [Mensagem de group-history]

[12:55] **Você:** {
    "resultado_da_simulacao_com_seguro": {
        "id_empregador": "0c23b5d9-6746-44b2-ba68-f23ea496557a",
        "cet_anual": 79.3119,
        "cet_mensal": 4.98665,
        "info_seguradora": {
            "id_empresa_seguradora": "b1316746-f84d-4fed-a70b-0bb0130e2703",
            "id_externo": "SM-100000742-9",
            "valor_seguro": 167.99,
            "valor_emprestimo": 1768.35,
            "numero_parcelas": 36,
            "data_ultima_parcela": "2027-01-22",
            "iof": 0
        },
        "taxa_anual": 60.1,
        "taxa_mensal": 4,
        "valor_iof": 58.46,
        "valor_seguro": 167.99,
        "valor_total_divida": 3600,
        "valor_total_financiado": 1768.35,
        "valor_total_taxa_mensal": 1831.65,
        "numero_parcelas": 36,
        "valor_parcela": 100,
        "valor_solicitado": 1541.9,
        "processor_name": "BMP_MOCK",
        "parcelas": [
            {
                "dias": 76,
                "dt_vencimento": "2027-01-25T00:00:00",
                "parcela_numero": 1,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 100,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1853.08
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-02-25T00:00:00",
                "parcela_numero": 2,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 200,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1829.72
            },
            {
                "dias": 28,
                "dt_vencimento": "2027-03-25T00:00:00",
                "parcela_numero": 3,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 300,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1797.94
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-04-25T00:00:00",
                "parcela_numero": 4,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 400,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1772.3
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-05-25T00:00:00",
                "parcela_numero": 5,
                "vlr_amortizacao": 25.16,
                "vlr_juros_acumulado": 474.84,
                "vlr_juros_mensal": 74.84,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1743.19
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-06-25T00:00:00",
                "parcela_numero": 6,
                "vlr_amortizacao": 27.9,
                "vlr_juros_acumulado": 546.94,
                "vlr_juros_mensal": 72.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1715.29
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-07-25T00:00:00",
                "parcela_numero": 7,
                "vlr_amortizacao": 31.39,
                "vlr_juros_acumulado": 615.55,
                "vlr_juros_mensal": 68.61,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1683.9
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-08-25T00:00:00",
                "parcela_numero": 8,
                "vlr_amortizacao": 30.35,
                "vlr_juros_acumulado": 685.2,
                "vlr_juros_mensal": 69.65,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1653.55
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-09-25T00:00:00",
                "parcela_numero": 9,
                "vlr_amortizacao": 31.61,
                "vlr_juros_acumulado": 753.59,
                "vlr_juros_mensal": 68.39,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1621.94
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-10-25T00:00:00",
                "parcela_numero": 10,
                "vlr_amortizacao": 35.12,
                "vlr_juros_acumulado": 818.47,
                "vlr_juros_mensal": 64.88,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1586.82
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-11-25T00:00:00",
                "parcela_numero": 11,
                "vlr_amortizacao": 34.37,
                "vlr_juros_acumulado": 884.1,
                "vlr_juros_mensal": 65.63,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1552.45
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-12-25T00:00:00",
                "parcela_numero": 12,
                "vlr_amortizacao": 37.9,
                "vlr_juros_acumulado": 946.2,
                "vlr_juros_mensal": 62.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1514.55
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-01-25T00:00:00",
                "parcela_numero": 13,
                "vlr_amortizacao": 37.36,
                "vlr_juros_acumulado": 1008.84,
                "vlr_juros_mensal": 62.64,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1477.19
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-02-25T00:00:00",
                "parcela_numero": 14,
                "vlr_amortizacao": 38.9,
                "vlr_juros_acumulado": 1069.94,
                "vlr_juros_mensal": 61.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1438.29
            },
            {
                "dias": 29,
                "dt_vencimento": "2028-03-25T00:00:00",
                "parcela_numero": 15,
                "vlr_amortizacao": 44.42,
                "vlr_juros_acumulado": 1125.52,
                "vlr_juros_mensal": 55.58,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1393.87
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-04-25T00:00:00",
                "parcela_numero": 16,
                "vlr_amortizacao": 42.35,
                "vlr_juros_acumulado": 1183.17,
                "vlr_juros_mensal": 57.65,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1351.52
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-05-25T00:00:00",
                "parcela_numero": 17,
                "vlr_amortizacao": 45.94,
                "vlr_juros_acumulado": 1237.23,
                "vlr_juros_mensal": 54.06,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1305.58
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-06-25T00:00:00",
                "parcela_numero": 18,
                "vlr_amortizacao": 46,
                "vlr_juros_acumulado": 1291.23,
                "vlr_juros_mensal": 54,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1259.58
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-07-25T00:00:00",
                "parcela_numero": 19,
                "vlr_amortizacao": 49.62,
                "vlr_juros_acumulado": 1341.61,
                "vlr_juros_mensal": 50.38,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1209.96
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-08-25T00:00:00",
                "parcela_numero": 20,
                "vlr_amortizacao": 49.96,
                "vlr_juros_acumulado": 1391.65,
                "vlr_juros_mensal": 50.04,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1160
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-09-25T00:00:00",
                "parcela_numero": 21,
                "vlr_amortizacao": 52.02,
                "vlr_juros_acumulado": 1439.63,
                "vlr_juros_mensal": 47.98,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1107.98
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-10-25T00:00:00",
                "parcela_numero": 22,
                "vlr_amortizacao": 55.68,
                "vlr_juros_acumulado": 1483.95,
                "vlr_juros_mensal": 44.32,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1052.3
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-11-25T00:00:00",
                "parcela_numero": 23,
                "vlr_amortizacao": 56.48,
                "vlr_juros_acumulado": 1527.47,
                "vlr_juros_mensal": 43.52,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 995.82
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-12-25T00:00:00",
                "parcela_numero": 24,
                "vlr_amortizacao": 60.17,
                "vlr_juros_acumulado": 1567.3,
                "vlr_juros_mensal": 39.83,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 935.65
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-01-25T00:00:00",
                "parcela_numero": 25,
                "vlr_amortizacao": 61.3,
                "vlr_juros_acumulado": 1606,
                "vlr_juros_mensal": 38.7,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 874.35
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-02-25T00:00:00",
                "parcela_numero": 26,
                "vlr_amortizacao": 63.84,
                "vlr_juros_acumulado": 1642.16,
                "vlr_juros_mensal": 36.16,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 810.51
            },
            {
                "dias": 28,
                "dt_vencimento": "2029-03-25T00:00:00",
                "parcela_numero": 27,
                "vlr_amortizacao": 69.78,
                "vlr_juros_acumulado": 1672.38,
                "vlr_juros_mensal": 30.22,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 740.73
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-04-25T00:00:00",
                "parcela_numero": 28,
                "vlr_amortizacao": 69.36,
                "vlr_juros_acumulado": 1703.02,
                "vlr_juros_mensal": 30.64,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 671.37
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-05-25T00:00:00",
                "parcela_numero": 29,
                "vlr_amortizacao": 73.15,
                "vlr_juros_acumulado": 1729.87,
                "vlr_juros_mensal": 26.85,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 598.22
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-06-25T00:00:00",
                "parcela_numero": 30,
                "vlr_amortizacao": 75.26,
                "vlr_juros_acumulado": 1754.61,
                "vlr_juros_mensal": 24.74,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 522.96
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-07-25T00:00:00",
                "parcela_numero": 31,
                "vlr_amortizacao": 79.08,
                "vlr_juros_acumulado": 1775.53,
                "vlr_juros_mensal": 20.92,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 443.88
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-08-25T00:00:00",
                "parcela_numero": 32,
                "vlr_amortizacao": 81.64,
                "vlr_juros_acumulado": 1793.89,
                "vlr_juros_mensal": 18.36,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 362.24
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-09-25T00:00:00",
                "parcela_numero": 33,
                "vlr_amortizacao": 85.02,
                "vlr_juros_acumulado": 1808.87,
                "vlr_juros_mensal": 14.98,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 277.22
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-10-25T00:00:00",
                "parcela_numero": 34,
                "vlr_amortizacao": 88.91,
                "vlr_juros_acumulado": 1819.96,
                "vlr_juros_mensal": 11.09,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 188.31
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-11-25T00:00:00",
                "parcela_numero": 35,
                "vlr_amortizacao": 92.21,
                "vlr_juros_acumulado": 1827.75,
                "vlr_juros_mensal": 7.79,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 96.1
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-12-25T00:00:00",
                "parcela_numero": 36,
                "vlr_amortizacao": 96.1,
                "vlr_juros_acumulado": 1831.65,
                "vlr_juros_mensal": 3.9,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 0
            }
        ]
    }
}

[12:56] **Você:** {
    "resultado_da_simulacao_com_seguro": {
        "id_empregador": "0c23b5d9-6746-44b2-ba68-f23ea496557a",
        "cet_anual": 79.3119,
        "cet_mensal": 4.98665,
        "info_seguradora": {
            "id_empresa_seguradora": "b1316746-f84d-4fed-a70b-0bb0130e2703",
            "id_externo": "SM-100000743-7",
            "valor_seguro": 167.99,
            "valor_emprestimo": 1768.35,
            "numero_parcelas": 36,
            "data_ultima_parcela": "2027-01-22",
            "iof": 0
        },
        "taxa_anual": 60.1,
        "taxa_mensal": 4,
        "valor_iof": 58.46,
        "valor_seguro": 167.99,
        "valor_total_divida": 3600,
        "valor_total_financiado": 1768.35,
        "valor_total_taxa_mensal": 1831.65,
        "numero_parcelas": 36,
        "valor_parcela": 100,
        "valor_solicitado": 1541.9,
        "processor_name": "BMP_MOCK",
        "parcelas": [
            {
                "dias": 76,
                "dt_vencimento": "2027-01-25T00:00:00",
                "parcela_numero": 1,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 100,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1853.08
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-02-25T00:00:00",
                "parcela_numero": 2,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 200,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1829.72
            },
            {
                "dias": 28,
                "dt_vencimento": "2027-03-25T00:00:00",
                "parcela_numero": 3,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 300,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1797.94
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-04-25T00:00:00",
                "parcela_numero": 4,
                "vlr_amortizacao": 0,
                "vlr_juros_acumulado": 400,
                "vlr_juros_mensal": 100,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1772.3
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-05-25T00:00:00",
                "parcela_numero": 5,
                "vlr_amortizacao": 25.16,
                "vlr_juros_acumulado": 474.84,
                "vlr_juros_mensal": 74.84,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1743.19
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-06-25T00:00:00",
                "parcela_numero": 6,
                "vlr_amortizacao": 27.9,
                "vlr_juros_acumulado": 546.94,
                "vlr_juros_mensal": 72.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1715.29
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-07-25T00:00:00",
                "parcela_numero": 7,
                "vlr_amortizacao": 31.39,
                "vlr_juros_acumulado": 615.55,
                "vlr_juros_mensal": 68.61,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1683.9
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-08-25T00:00:00",
                "parcela_numero": 8,
                "vlr_amortizacao": 30.35,
                "vlr_juros_acumulado": 685.2,
                "vlr_juros_mensal": 69.65,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1653.55
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-09-25T00:00:00",
                "parcela_numero": 9,
                "vlr_amortizacao": 31.61,
                "vlr_juros_acumulado": 753.59,
                "vlr_juros_mensal": 68.39,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1621.94
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-10-25T00:00:00",
                "parcela_numero": 10,
                "vlr_amortizacao": 35.12,
                "vlr_juros_acumulado": 818.47,
                "vlr_juros_mensal": 64.88,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1586.82
            },
            {
                "dias": 31,
                "dt_vencimento": "2027-11-25T00:00:00",
                "parcela_numero": 11,
                "vlr_amortizacao": 34.37,
                "vlr_juros_acumulado": 884.1,
                "vlr_juros_mensal": 65.63,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1552.45
            },
            {
                "dias": 30,
                "dt_vencimento": "2027-12-25T00:00:00",
                "parcela_numero": 12,
                "vlr_amortizacao": 37.9,
                "vlr_juros_acumulado": 946.2,
                "vlr_juros_mensal": 62.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1514.55
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-01-25T00:00:00",
                "parcela_numero": 13,
                "vlr_amortizacao": 37.36,
                "vlr_juros_acumulado": 1008.84,
                "vlr_juros_mensal": 62.64,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1477.19
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-02-25T00:00:00",
                "parcela_numero": 14,
                "vlr_amortizacao": 38.9,
                "vlr_juros_acumulado": 1069.94,
                "vlr_juros_mensal": 61.1,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1438.29
            },
            {
                "dias": 29,
                "dt_vencimento": "2028-03-25T00:00:00",
                "parcela_numero": 15,
                "vlr_amortizacao": 44.42,
                "vlr_juros_acumulado": 1125.52,
                "vlr_juros_mensal": 55.58,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1393.87
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-04-25T00:00:00",
                "parcela_numero": 16,
                "vlr_amortizacao": 42.35,
                "vlr_juros_acumulado": 1183.17,
                "vlr_juros_mensal": 57.65,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1351.52
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-05-25T00:00:00",
                "parcela_numero": 17,
                "vlr_amortizacao": 45.94,
                "vlr_juros_acumulado": 1237.23,
                "vlr_juros_mensal": 54.06,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1305.58
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-06-25T00:00:00",
                "parcela_numero": 18,
                "vlr_amortizacao": 46,
                "vlr_juros_acumulado": 1291.23,
                "vlr_juros_mensal": 54,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1259.58
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-07-25T00:00:00",
                "parcela_numero": 19,
                "vlr_amortizacao": 49.62,
                "vlr_juros_acumulado": 1341.61,
                "vlr_juros_mensal": 50.38,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1209.96
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-08-25T00:00:00",
                "parcela_numero": 20,
                "vlr_amortizacao": 49.96,
                "vlr_juros_acumulado": 1391.65,
                "vlr_juros_mensal": 50.04,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1160
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-09-25T00:00:00",
                "parcela_numero": 21,
                "vlr_amortizacao": 52.02,
                "vlr_juros_acumulado": 1439.63,
                "vlr_juros_mensal": 47.98,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1107.98
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-10-25T00:00:00",
                "parcela_numero": 22,
                "vlr_amortizacao": 55.68,
                "vlr_juros_acumulado": 1483.95,
                "vlr_juros_mensal": 44.32,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 1052.3
            },
            {
                "dias": 31,
                "dt_vencimento": "2028-11-25T00:00:00",
                "parcela_numero": 23,
                "vlr_amortizacao": 56.48,
                "vlr_juros_acumulado": 1527.47,
                "vlr_juros_mensal": 43.52,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 995.82
            },
            {
                "dias": 30,
                "dt_vencimento": "2028-12-25T00:00:00",
                "parcela_numero": 24,
                "vlr_amortizacao": 60.17,
                "vlr_juros_acumulado": 1567.3,
                "vlr_juros_mensal": 39.83,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 935.65
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-01-25T00:00:00",
                "parcela_numero": 25,
                "vlr_amortizacao": 61.3,
                "vlr_juros_acumulado": 1606,
                "vlr_juros_mensal": 38.7,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 874.35
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-02-25T00:00:00",
                "parcela_numero": 26,
                "vlr_amortizacao": 63.84,
                "vlr_juros_acumulado": 1642.16,
                "vlr_juros_mensal": 36.16,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 810.51
            },
            {
                "dias": 28,
                "dt_vencimento": "2029-03-25T00:00:00",
                "parcela_numero": 27,
                "vlr_amortizacao": 69.78,
                "vlr_juros_acumulado": 1672.38,
                "vlr_juros_mensal": 30.22,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 740.73
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-04-25T00:00:00",
                "parcela_numero": 28,
                "vlr_amortizacao": 69.36,
                "vlr_juros_acumulado": 1703.02,
                "vlr_juros_mensal": 30.64,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 671.37
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-05-25T00:00:00",
                "parcela_numero": 29,
                "vlr_amortizacao": 73.15,
                "vlr_juros_acumulado": 1729.87,
                "vlr_juros_mensal": 26.85,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 598.22
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-06-25T00:00:00",
                "parcela_numero": 30,
                "vlr_amortizacao": 75.26,
                "vlr_juros_acumulado": 1754.61,
                "vlr_juros_mensal": 24.74,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 522.96
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-07-25T00:00:00",
                "parcela_numero": 31,
                "vlr_amortizacao": 79.08,
                "vlr_juros_acumulado": 1775.53,
                "vlr_juros_mensal": 20.92,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 443.88
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-08-25T00:00:00",
                "parcela_numero": 32,
                "vlr_amortizacao": 81.64,
                "vlr_juros_acumulado": 1793.89,
                "vlr_juros_mensal": 18.36,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 362.24
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-09-25T00:00:00",
                "parcela_numero": 33,
                "vlr_amortizacao": 85.02,
                "vlr_juros_acumulado": 1808.87,
                "vlr_juros_mensal": 14.98,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 277.22
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-10-25T00:00:00",
                "parcela_numero": 34,
                "vlr_amortizacao": 88.91,
                "vlr_juros_acumulado": 1819.96,
                "vlr_juros_mensal": 11.09,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 188.31
            },
            {
                "dias": 31,
                "dt_vencimento": "2029-11-25T00:00:00",
                "parcela_numero": 35,
                "vlr_amortizacao": 92.21,
                "vlr_juros_acumulado": 1827.75,
                "vlr_juros_mensal": 7.79,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 96.1
            },
            {
                "dias": 30,
                "dt_vencimento": "2029-12-25T00:00:00",
                "parcela_numero": 36,
                "vlr_amortizacao": 96.1,
                "vlr_juros_acumulado": 1831.65,
                "vlr_juros_mensal": 3.9,
                "vlr_prestacao_total": 100,
                "vlr_saldo_devedor": 0
            }
        ]
    }
}

---

## 11 de novembro de 2026

[10:19] **[Granatech]:** Bom dia, pessoal. Tudo bem?

[10:19] **[Granatech]:** Nosso time já está validando, retorno aqui já já

[10:59] **Você:** Bom dia, tudo sim e por aí?

[10:59] **Você:**
> _[Granatech]: Nosso time já está validando, retorno aqui já já_
Blz [Granatech] valeu

[12:51] **[Granatech]:** Boa tarde! Tudo certinho, pessoal. Segue segunda e última etapa de homologação.

[12:51] **[Granatech]:** Homologação Granatech | Fase 2: Fluxo de Contratação
Recebemos as evidências da Fase 1 e está tudo certo! Agora, vamos para o fluxo crítico de contratação.
2 Evidências de Contratação com Sucesso (Validando a recepção do status via Webhook).
1 Evidência de Erro de Contratação (Para garantirmos que seu sistema trata as mensagens de erro e notificações de falha)

[12:52] **[Granatech]:** [Documento] GRANATECH3-Propostas-050326-173127 (2) (1) (2).pdf

[12:52] **[Granatech]:** [Documento] Rotas API-Granatech - Contratacao-Consulta-dev -Corban MEX.postman_collection.json
