// Códigos do grafo e da API em português, num lugar só.

export const ETAPAS: Record<string, string> = {
  abertura: "Abertura",
  identificacao: "Identificação",
  triagem: "Triagem",
  empresa: "Empresa",
  consentimento: "Consentimento",
  consultando: "Consultando",
  escolha_vinculo: "Escolha do vínculo",
  oferta: "Oferta",
  aceite: "Aceite",
  dados_proposta: "Dados da proposta",
  proposta: "Proposta",
  formalizacao: "Formalização",
  pago: "Pago",
  nao_elegivel: "Não elegível",
  recontato: "Recontato",
  handoff: "Handoff",
  inss: "Portabilidade INSS",
};

export const MOTIVOS_HANDOFF: Record<string, string> = {
  aceite_clt: "Cliente aceitou a oferta",
  aceitou_portabilidade: "Cliente aceitou a portabilidade",
  acima_do_teto: "Valor acima do teto",
  brasilapi_indisponivel: "BrasilAPI fora do ar",
  consulta_com_erro: "Consulta com erro",
  cota_esgotada: "Cota esgotada",
  dado_invalido_repetido: "Dado inválido duas vezes",
  dados_cliente_nao_informados: "Dados não informados",
  dados_divergentes: "Dados divergentes",
  dados_tomador_falhou: "Envio dos dados falhou",
  erro_interno: "Erro interno",
  especie_nao_atendida: "Espécie não atendida",
  extrato_ilegivel_repetido: "Extrato ilegível",
  falha_pagamento: "Falha no pagamento",
  falha_pagamento_repetida: "Pagamento falhou de novo",
  granatech_indisponivel: "Granatech fora do ar",
  hiscon_nao_conferiu: "Extrato não conferiu",
  idade_fora_regra: "Idade fora da regra",
  limite_simulacoes: "Limite de simulações",
  link_indisponivel: "Link indisponível",
  mudou_publico: "Mudou de produto",
  pediu_cancelamento: "Pediu cancelamento",
  pediu_humano: "Pediu uma pessoa",
  proposta_incerta: "Proposta incerta",
  proposta_sem_seguro: "Proposta sem seguro",
  revisao_banco: "Revisão do banco",
  sem_consentimento: "Sem consentimento",
  sem_portabilidade: "Sem portabilidade",
  sem_resposta: "Sem resposta",
  status_desconhecido: "Status desconhecido",
  termo_falhou: "Termo falhou",
  handoff: "Handoff",
};

export const ATENCAO: Record<string, string> = {
  sem_resposta: "Sem resposta",
  handoff: "Aguardando equipe",
  dinheiro: "Falando de valores",
  envio_falhou: "Envio falhou",
};

// Modelos aprovados na Meta que o painel envia. O texto fica cadastrado lá.
export const MODELOS: Record<string, string> = {
  atualizacao_pedido: "Atualização do pedido",
  autorizacao_pendente: "Autorização pendente",
  dados_bancarios_pendentes: "Dados bancários pendentes",
  pagamento_confirmado: "Pagamento confirmado",
};

export const PUBLICOS: Record<string, string> = {
  clt: "Crédito do Trabalhador (CLT)",
  inss: "Portabilidade INSS",
  indefinido: "Ainda não identificado",
};

export const AUTORES: Record<string, string> = {
  cliente: "Cliente",
  ia: "IA",
  atendente: "Equipe",
  sistema: "Sistema",
};

export const rotulo = (mapa: Record<string, string>, codigo: string) => mapa[codigo] ?? codigo;

// "agora", "há 3 min", "há 2 h", "ontem", "12/11".
export function relativo(iso: string, agora: number): string {
  const minutos = Math.max(0, Math.floor((agora - new Date(iso).getTime()) / 60000));
  if (minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  if (horas < 48) return "ontem";
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export const NOS: Record<string, string> = {
  __start__: "Entrada",
  __end__: "Fim",
  boas_vindas: "Deu boas-vindas",
  classify_intent: "Classificou a mensagem",
  generate_answer: "Respondeu pela FAQ",
  clt: "Jornada CLT",
  pedir_texto: "Pediu texto",
  handoff: "Passou para a equipe",
  decline_offer: "Registrou a recusa",
  read_statement: "Leu o extrato",
  check_customer_data: "Conferiu os dados",
  collect_customer_data: "Pediu dados",
  calculate_portability: "Calculou a portabilidade",
  present_offer: "Apresentou a oferta",
};

export const CHAMADAS: Record<string, string> = {
  jev: "Classificador",
  llm: "Modelo (FAQ)",
  visao: "Leitura de anexo",
  anexo: "Download de anexo",
  granatech: "Granatech",
  brasilapi: "BrasilAPI",
  webhook: "Webhook",
};

// Aceita o número como texto ("300.00"); o que não for número sai como veio.
export function reais(valor: string | number | null | undefined): string {
  const numero = Number(valor);
  if (valor === undefined || valor === null || valor === "" || Number.isNaN(numero))
    return `R$ ${valor ?? "—"}`;
  return numero.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

// Status da proposta na Granatech, como a equipe fala deles.
export const STATUS_PROPOSTA: Record<string, string> = {
  PENDING_CONFIRMATION: "Aguardando confirmação",
  PENDING_USER_REVIEW: "Aguardando revisão",
  PENDING_FORMALIZATION: "Aguardando assinatura",
  PENDING_BANK_ANALYSIS: "Banco analisando",
  PENDING_PAYMENT: "Pagamento a caminho",
  PENDING_REFORMALIZATION: "Refazer assinatura",
  REPROVED: "Reprovada",
  CANCELED: "Cancelada",
  CANCELED_BY_CLIENT: "Cancelada pelo cliente",
  PAYED: "Paga",
};

export const TIPOS_DE_PROVA: Record<string, string> = {
  consulta: "Autorizou a consulta",
  proposta: "Aceitou a proposta",
};

// US$ com 4 casas para valores pequenos (um turno custa frações de centavo).
export function dolar(valor: number): string {
  if (valor > 0 && valor < 0.0001) return "< US$ 0,0001";
  const casas = valor !== 0 && Math.abs(valor) < 1 ? 4 : 2;
  const texto = valor.toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
  return `US$ ${texto}`;
}

export const tokens = (n: number) => n.toLocaleString("pt-BR");

// O que o atendente lê no lugar do código da Granatech. O que não estiver aqui
// aparece como veio: melhor o código cru do que um rótulo errado.
export const SITUACAO_DA_CONSULTA: Record<string, string> = {
  AWAITING_CLIENT_AUTHORIZATION: "Aguardando o cliente autorizar",
  PROCESSING: "Em processamento",
  SUCCESS: "Concluída",
  PENDING: "Pendente",
  NO_MARGIN: "Sem margem",
  USED: "Já usada",
  UNEXPECTED_ERROR: "Erro inesperado",
  FIDUCIARY_INSTITUTION_NO_AUTHORIZATION: "Instituição sem autorização",
  WORKER_MUST_CANCEL_RETURN_REQUEST: "Cancelamento pendente",
};

export const SITUACAO_DA_PROPOSTA: Record<string, string> = {
  PENDING_CONFIRMATION: "Aguardando confirmação",
  AGUARDANDO_CONFIRMACAO: "Aguardando confirmação",
  PENDING_USER_REVIEW: "Aguardando revisão",
  AGUARDANDO_REVISAO_USUARIO: "Aguardando revisão",
  PENDING_FORMALIZATION: "Aguardando formalização",
  AGUARDANDO_FORMALIZACAO: "Aguardando formalização",
  PENDING_BANK_ANALYSIS: "Em análise no banco",
  AGUARDANDO_ANALISE_BANCO: "Em análise no banco",
  PENDING_PAYMENT: "Aguardando pagamento",
  PENDING_REFORMALIZATION: "Refazer a identidade",
  REFAZER_SEGURANCA_IDENTIDADE: "Refazer a identidade",
  SUCESSO_SEGURANCA_IDENTIDADE: "Identidade aprovada",
  BLOQUEIO_DE_SALDO_EM_ANDAMENTO: "Bloqueando o saldo",
  BLOQUEIO_SALDO: "Saldo bloqueado",
  FORMALIZACAO_EM_ANDAMENTO: "Formalização em andamento",
  FALHA_PAGAMENTO: "Falha no pagamento",
  REPROVED: "Reprovada",
  REPROVADO: "Reprovada",
  CANCELED: "Cancelada",
  CANCELED_BY_CLIENT: "Cancelada pelo cliente",
  PAYED: "Paga",
  PAGO: "Paga",
  PROPOSTA_PAGA: "Paga",
};

/** Status e `tipo_notificacao` dizem a mesma coisa em dialetos diferentes:
 *  mostra o rótulo uma vez só, e os dois apenas quando divergem. */
export function situacaoDaProposta(
  status: string | null | undefined,
  notificacao: string | null | undefined,
): string {
  const doStatus = status ? SITUACAO_DA_PROPOSTA[status] : undefined;
  const daNotificacao = notificacao ? SITUACAO_DA_PROPOSTA[notificacao] : undefined;
  if (doStatus && daNotificacao && doStatus !== daNotificacao) {
    return `${doStatus} · ${daNotificacao}`;
  }
  return doStatus ?? daNotificacao ?? status ?? notificacao ?? "—";
}

/** As situações na ordem em que a proposta anda; o filtro do painel segue essa
 *  ordem. Só entram códigos que podem aparecer na coluna `status`. */
export const SITUACOES_DA_PROPOSTA = [
  "PENDING_CONFIRMATION",
  "PENDING_USER_REVIEW",
  "PENDING_FORMALIZATION",
  "BLOQUEIO_DE_SALDO_EM_ANDAMENTO",
  "BLOQUEIO_SALDO",
  "FORMALIZACAO_EM_ANDAMENTO",
  "PENDING_BANK_ANALYSIS",
  "PENDING_PAYMENT",
  "PENDING_REFORMALIZATION",
  "PAYED",
  "REPROVED",
  "CANCELED",
  "CANCELED_BY_CLIENT",
] as const;

export const SITUACOES_DA_CONSULTA = [
  "AWAITING_CLIENT_AUTHORIZATION",
  "PROCESSING",
  "PENDING",
  "SUCCESS",
  "NO_MARGIN",
  "USED",
  "UNEXPECTED_ERROR",
  "FIDUCIARY_INSTITUTION_NO_AUTHORIZATION",
  "WORKER_MUST_CANCEL_RETURN_REQUEST",
] as const;
