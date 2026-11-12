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
