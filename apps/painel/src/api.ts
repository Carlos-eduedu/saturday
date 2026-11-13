// Cliente da API admin. Mesma origem que o painel: o cookie de sessão vai
// sozinho; o CSRF vem de `/admin/eu` e acompanha toda ação que muda estado.

export type Perfil = "atendente" | "gestor";
export type Atendimento = "ia" | "handoff" | "assumida";

export interface Eu {
  id: string;
  email: string;
  nome: string;
  perfil: Perfil;
  csrf: string;
}

export interface Resumo {
  id: string;
  canal: string;
  atendimento: Atendimento;
  atendente_id: string | null;
  telefone: string | null;
  ultima_entrada_em: string | null;
  nao_lida: boolean;
  janela_aberta: boolean;
  ultima_mensagem: { autor: string; texto: string; em: string } | null;
  etapa: string | null;
  motivo_handoff: string | null;
  aguardando_desde: string | null;
  envio_falhou: boolean;
  atencao: string[];
  ultima_atividade: string;
}

export interface Mensagem {
  id: number;
  direcao: "entrada" | "saida";
  autor: "cliente" | "ia" | "atendente" | "sistema";
  usuario_id: string | null;
  conteudo: string;
  status_entrega: string | null;
  criada_em: string;
  anexos: { mime_type: string }[];
}

export interface Detalhe extends Resumo {
  mensagens: Mensagem[];
  modelos: string[];
}

export interface Ficha {
  nome: string | null;
  dados: Partial<Record<CampoSensivel, string>>;
  uf: string | null;
  publico: string | null;
  handoff_reason: string | null;
  portabilidade: unknown;
  // O que a IA ofereceu (valores como texto), o que o banco registrou e as provas do SIM.
  oferta: {
    liberado: string;
    valor_parcela: string;
    numero_parcelas: number;
    taxa_mensal: string;
    cet_mensal: string;
    valor_seguro: string;
    seguro_aplicado: boolean;
    limitado_ao_teto: boolean;
  } | null;
  proposta: {
    id: number;
    status: string | null;
    estado_envio: string;
    valor_parcela: string;
    numero_parcelas: number;
    atualizada_em: string;
    difere_da_oferta: boolean;
  } | null;
  consentimentos: {
    tipo: string;
    versao: string;
    texto_mostrado: string;
    resposta_literal: string;
    criada_em: string;
  }[];
}

export type CampoSensivel = "cpf" | "telefone" | "data_nascimento" | "email";

export interface Alerta {
  id: number;
  tipo: string;
  conversa_id: string | null;
  detalhe: Record<string, unknown> | null;
  criado_em: string;
}

export interface Cota {
  mes: { usadas: number; teto: number };
  dia: { usadas: number; teto: number };
}

export interface Usuario {
  id: string;
  nome: string;
  email: string;
  perfil: Perfil;
}

// Linha da aba Usuários (só gestor).
export interface UsuarioGestao {
  id: string;
  nome: string;
  email: string;
  perfil: Perfil;
  situacao: "ativo" | "bloqueado" | "desativado";
  bloqueado_ate: string | null;
  criado_em: string;
  conversas_assumidas: number;
}

export interface NovoUsuario {
  nome: string;
  email: string;
  perfil: Perfil;
  senha: string;
}

export interface InstanciaEvolution {
  nome: string;
  estado: "open" | "connecting" | "close" | "refused" | string;
  telefone: string;
  conversas_7_dias: number;
}

export interface Canais {
  meta: { phone_number_id: string }[];
  evolution: { ativo: boolean; instancias: InstanciaEvolution[]; erro: string | null };
}

export interface DetalhesInstancia {
  webhook: {
    configurado: boolean;
    ativo: boolean;
    url: string;
    url_esperada: string;
    eventos: string[];
    eventos_esperados: string[];
    eventos_disponiveis: string[];
    por_evento: boolean;
    base64: boolean;
    autenticacao: "confere" | "diferente" | "ausente";
  };
  configuracoes: { nome: string; atual: boolean | null; padrao: boolean }[];
  mensagem_chamada: string;
  divergencias: string[];
}

export interface ConfiguracoesInstancia {
  rejectCall: boolean;
  groupsIgnore: boolean;
  alwaysOnline: boolean;
  readMessages: boolean;
  readStatus: boolean;
  syncFullHistory: boolean;
  msgCall: string;
}

export interface Qr {
  qr: string | null;
  estado: string;
}

export interface ChamadaTurno {
  nome: string;
  latencia_ms: number;
  status: string | null;
  custo_usd: number | null;
  tokens_entrada: number | null;
  tokens_saida: number | null;
}

export interface Turno {
  id: number;
  criado_em: string;
  caminho: string[];
  status: string | null;
  motivo: string | null;
  etapa: string | null;
  classificacao: {
    intencao: string | null;
    publico: string | null;
    confianca: number | null;
  } | null;
  chamadas: ChamadaTurno[];
  custo_usd: number | null;
  tokens: number | null;
}

export interface Trilha {
  custo_usd: number | null;
  tokens: number | null;
  turnos: Turno[];
}

export interface DiaDeCusto {
  dia: string;
  custo_usd: number;
  tokens: number;
  turnos: number;
}

export interface Custos {
  de: string;
  ate: string;
  total: { custo_usd: number; tokens: number; turnos: number };
  hoje: DiaDeCusto | null;
  dias: DiaDeCusto[];
  conversas_mais_caras: { id: string; telefone: string | null; canal: string; custo_usd: number }[];
}

// Aba Granatech (decisão 0013): consulta para todos, ações só para gestor.
export type Acoes = Record<string, string | null>; // null = pode; texto = motivo de não poder

export interface EventoGranatech {
  status: string | null;
  tipo_notificacao?: string | null;
  informacoes?: unknown;
  origem?: string;
  recebido_em: string;
}

export interface ConsultaGranatech {
  id: number;
  id_externo: string;
  cpf: string;
  status: string;
  conversa_id: string | null;
  tem_detalhe: boolean;
  criada_em: string;
  atualizada_em: string;
}

export interface ConsultaGranatechDetalhe extends ConsultaGranatech {
  historico: EventoGranatech[];
  vinculos: {
    id?: string;
    margem?: string | number;
    nome_empregador?: string;
    documento_empregador?: string;
    elegivel_empregador?: boolean;
    produtos?: { id?: string; nome?: string; parcelas?: unknown; taxa_mensal?: unknown }[];
  }[];
  idade: number | null;
  sexo: string | null;
  propostas: number[];
  etapa: string | null;
  acoes: Acoes;
}

export interface PropostaGranatech {
  id: number;
  id_externo: string | null;
  consulta_id: number;
  cpf: string;
  estado_envio: string;
  status: string | null;
  tipo_notificacao: string | null;
  valor_parcela: string;
  numero_parcelas: number;
  conversa_id: string | null;
  intencao_em: string;
  atualizada_em: string;
}

export interface PropostaGranatechDetalhe extends PropostaGranatech {
  historico: EventoGranatech[];
  etapa: string | null;
  oferta: Record<string, unknown> | null;
  conta_ativa: boolean;
  acoes: Acoes;
}

export interface FiltroGranatech {
  status?: string;
  desde?: string;
  ate?: string;
  cpf?: string;
}

export interface ContaNova {
  banco_codigo: string;
  agencia: string;
  digito_agencia: string;
  numero_conta: string;
  digito_conta: string;
  tipo_conta: "conta_corrente" | "conta_poupanca";
}

// Homologação Granatech pelo painel (decisão 0014): só gestor, fora de produção.
export type SituacaoRodada = "pendente" | "em_andamento" | "concluida" | "falhou" | "interrompida";

export type Rodada = {
  id: number;
  fase: 1 | 2;
  situacao: SituacaoRodada;
  pedido_por: string | null;
  criado_em: string | null;
  iniciado_em: string | null;
  terminado_em: string | null;
  erro: string | null;
  progresso: { total: number; ok: boolean[] };
};

export type ItemHomologacao = {
  fase: string;
  item: string;
  arquivo: string;
  ok: boolean;
  observacao: string;
};

export type RodadaDetalhe = Rodada & {
  itens_previstos: string[];
  itens: ItemHomologacao[];
  passos: ({ arquivo: string; horario?: string } & Record<string, unknown>)[];
};

export type Homologacao = {
  webhook_esperado: string | null;
  base_granatech: string;
  consultas_por_fase: Record<string, number>;
  rodadas: Rodada[];
};

export class ErroApi extends Error {
  constructor(
    readonly status: number,
    mensagem: string,
  ) {
    super(mensagem);
  }
}

let csrf = "";

export function guardarCsrf(token: string): void {
  csrf = token;
}

async function chamar<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
  const cabecalhos: Record<string, string> = {};
  if (metodo !== "GET") cabecalhos["X-CSRF-Token"] = csrf;
  if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  const resposta = await fetch(`/admin${caminho}`, {
    method: metodo,
    headers: cabecalhos,
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
    credentials: "same-origin",
  });
  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try {
      const json = (await resposta.json()) as { detail?: unknown };
      if (typeof json.detail === "string") detalhe = json.detail;
    } catch {
      // corpo sem JSON: fica o statusText
    }
    throw new ErroApi(resposta.status, detalhe);
  }
  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

export const api = {
  entrar: (email: string, senha: string) => chamar<Eu>("POST", "/login", { email, senha }),
  sair: () => chamar<void>("POST", "/logout"),
  eu: () => chamar<Eu>("GET", "/eu"),
  usuarios: () => chamar<Usuario[]>("GET", "/usuarios"),
  conversas: (fila: string, busca: string) => {
    const params = new URLSearchParams();
    if (fila) params.set("fila", fila);
    if (busca) params.set("busca", busca);
    return chamar<Resumo[]>("GET", `/conversas?${params}`);
  },
  conversa: (id: string) => chamar<Detalhe>("GET", `/conversas/${id}`),
  assumir: (id: string) => chamar<void>("POST", `/conversas/${id}/assumir`),
  devolver: (id: string) => chamar<void>("POST", `/conversas/${id}/devolver`),
  desfazer: (id: string) => chamar<void>("POST", `/conversas/${id}/desfazer`),
  transferir: (id: string, usuario_id: string) =>
    chamar<void>("POST", `/conversas/${id}/transferir`, { usuario_id }),
  enviar: (id: string, envio: { texto: string } | { modelo: string }) =>
    chamar<{ mensagem_id: number }>("POST", `/conversas/${id}/mensagens`, envio),
  ficha: (id: string) => chamar<Ficha>("GET", `/conversas/${id}/ficha`),
  revelar: (id: string, campo: CampoSensivel) =>
    chamar<{ campo: CampoSensivel; valor: string }>("POST", `/conversas/${id}/revelar`, { campo }),
  alertas: () => chamar<Alerta[]>("GET", "/alertas"),
  resolverAlerta: (id: number) => chamar<void>("POST", `/alertas/${id}/resolver`),
  cota: () => chamar<Cota>("GET", "/cota"),
  canais: () => chamar<Canais>("GET", "/canais"),
  gestaoUsuarios: () => chamar<UsuarioGestao[]>("GET", "/gestao/usuarios"),
  criarUsuario: (dados: NovoUsuario) => chamar<{ id: string }>("POST", "/gestao/usuarios", dados),
  editarUsuario: (id: string, dados: { nome: string; email: string; perfil: Perfil }) =>
    chamar<void>("PATCH", `/gestao/usuarios/${id}`, dados),
  redefinirSenha: (id: string, senha: string) =>
    chamar<void>("POST", `/gestao/usuarios/${id}/senha`, { senha }),
  desbloquearUsuario: (id: string) => chamar<void>("POST", `/gestao/usuarios/${id}/desbloquear`),
  desativarUsuario: (id: string) =>
    chamar<{ conversas_devolvidas: number }>("POST", `/gestao/usuarios/${id}/desativar`),
  reativarUsuario: (id: string) => chamar<void>("POST", `/gestao/usuarios/${id}/reativar`),
  turnos: (id: string) => chamar<Trilha>("GET", `/conversas/${id}/turnos`),
  custos: () => chamar<Custos>("GET", "/custos"),
  criarInstancia: (nome: string) => chamar<Qr>("POST", "/canais/evolution", { nome }),
  conectarInstancia: (nome: string) => chamar<Qr>("POST", `/canais/evolution/${nome}/conectar`),
  qrInstancia: (nome: string) => chamar<Qr>("GET", `/canais/evolution/${nome}/qr`),
  detalhesInstancia: (nome: string) =>
    chamar<DetalhesInstancia>("GET", `/canais/evolution/${nome}/detalhes`),
  configurarInstancia: (nome: string, valores: ConfiguracoesInstancia) =>
    chamar<void>("PUT", `/canais/evolution/${nome}/configuracoes`, valores),
  escolherEventos: (nome: string, eventos: string[]) =>
    chamar<void>("PUT", `/canais/evolution/${nome}/eventos`, { eventos }),
  reaplicarWebhook: (nome: string) => chamar<void>("POST", `/canais/evolution/${nome}/webhook`),
  desconectarInstancia: (nome: string) =>
    chamar<void>("POST", `/canais/evolution/${nome}/desconectar`),
  apagarInstancia: (nome: string) => chamar<void>("DELETE", `/canais/evolution/${nome}`),
  consultasGranatech: (filtro: FiltroGranatech) =>
    chamar<ConsultaGranatech[]>("GET", `/granatech/consultas?${parametros(filtro)}`),
  propostasGranatech: (filtro: FiltroGranatech) =>
    chamar<PropostaGranatech[]>("GET", `/granatech/propostas?${parametros(filtro)}`),
  consultaGranatech: (id: number) =>
    chamar<ConsultaGranatechDetalhe>("GET", `/granatech/consultas/${id}`),
  propostaGranatech: (id: number) =>
    chamar<PropostaGranatechDetalhe>("GET", `/granatech/propostas/${id}`),
  revelarCpfGranatech: (consultaId: number) =>
    chamar<{ campo: "cpf"; valor: string }>("POST", `/granatech/consultas/${consultaId}/revelar`),
  bancosGranatech: () => chamar<{ codigo: string; nome: string }[]>("GET", "/granatech/bancos"),
  reconciliar: (id: number) =>
    chamar<{ achada: boolean; id_externo?: string }>("POST", `/granatech/propostas/${id}/reconciliar`),
  reenviarLink: (id: number) => chamar<void>("POST", `/granatech/propostas/${id}/reenviar-link`),
  cancelarProposta: (id: number, motivo: string) =>
    chamar<void>("POST", `/granatech/propostas/${id}/cancelar`, { motivo }),
  corrigirConta: (id: number, conta: ContaNova) =>
    chamar<void>("POST", `/granatech/propostas/${id}/conta`, conta),
  atualizarDetalhe: (id: number) =>
    chamar<{ pronto: boolean }>("POST", `/granatech/consultas/${id}/atualizar-detalhe`),
  homologacao: () => chamar<Homologacao>("GET", "/granatech/homologacao"),
  rodada: (id: number) => chamar<RodadaDetalhe>("GET", `/granatech/homologacao/${id}`),
  pedirRodada: (fase: 1 | 2) => chamar<Rodada>("POST", "/granatech/homologacao", { fase }),
};

function parametros(filtro: FiltroGranatech): URLSearchParams {
  const params = new URLSearchParams();
  for (const [chave, valor] of Object.entries(filtro)) if (valor) params.set(chave, valor);
  return params;
}

export const midiaUrl = (mensagemId: number, indice: number) =>
  `/admin/midia/${mensagemId}/${indice}`;

// Download navegando: o cookie da sessão vai junto e o nome do arquivo vem do
// `Content-Disposition` da resposta.
export const exportarUrl = (conversaId: string) => `/admin/conversas/${conversaId}/exportar`;
export const rodadaZipUrl = (rodadaId: number) => `/admin/granatech/homologacao/${rodadaId}/zip`;
