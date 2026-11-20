// Cliente da API admin. Mesma origem que o painel: o cookie de sessão vai
// sozinho; o CSRF vem de `/admin/eu` e acompanha toda ação que muda estado.

export type Perfil = "atendente" | "gestor";
export type Atendimento = "ia" | "handoff" | "assumida";

export interface Eu {
  id: string;
  email: string;
  nome: string;
  perfil: Perfil;
  pode_editar_agente: boolean;
  // Perfil da seção "Você": telefone (só dígitos) e o endereço da foto.
  telefone: string | null;
  foto: string | null;
  // Conversas do telefone do perfil são de teste (decisão 0020).
  pode_testar_fluxos: boolean;
  // Função (o gestor preenche) e disponibilidade (a própria pessoa marca).
  cargo: string | null;
  disponivel: boolean;
  // Senha definida pelo gestor: até trocar, a API só deixa trocar a senha e sair.
  trocar_senha: boolean;
  csrf: string;
}

/** Contagens das filas do inbox em toda a base (`/conversas/contagens`). */
export interface Contagens {
  todas: number;
  ia: number;
  handoff: number;
  assumida: number;
  minhas: number;
  atencao: number;
}

export interface Resumo {
  id: string;
  canal: string;
  atendimento: Atendimento;
  atendente_id: string | null;
  telefone: string | null;
  ultima_entrada_em: string | null;
  nao_lida: boolean;
  // O que o canal permite agora, pronto do servidor (`painel/canal.py`):
  // a tela não compara `canal` para decidir envio.
  envia: boolean;
  janela: "aberta" | "fechada" | null;
  modelos: string[];
  // Conversa da Evolution cuja instância foi apagada: sem envio, com aviso.
  instancia_apagada: boolean;
  ultima_mensagem: { autor: string; texto: string; em: string } | null;
  etapa: string | null;
  // Nome do membro testador dono do telefone (decisão 0020), ou null.
  membro: string | null;
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
  // Procedência da fala da IA (decisão 0018): chave nula com turno = o modelo
  // escreveu; os dois nulos = linha anterior à decisão.
  turno_id: number | null;
  chave_mensagem: string | null;
  // Ramo da oferta que a fala fixa apresenta; nulo nas outras falas.
  ramo_da_oferta: string | null;
  anexos: { mime_type: string; nome?: string | null }[];
}

export interface Detalhe extends Resumo {
  mensagens: Mensagem[];
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
  // A última oferta mostrada ao cliente, de qualquer ramo (clt, contrato_novo,
  // portabilidade ou icred), com os reais que a fala dela cita, como texto.
  // `situacao`: "vigente" ou "recusada" (recusada, segue valendo para conferir).
  oferta_vigente: { ramo: string; situacao: string; valores: string[] } | null;
  // A oferta que o estado guarda de cada ramo: a fala fixa de oferta é
  // conferida contra a do próprio ramo. `situacao` nula = oferta anterior.
  ofertas: Record<string, { situacao: string | null; valores: string[] }>;
  // A faixa da sobra na portabilidade, em reais inteiros como na fala; só
  // enquanto ela for a oferta vigente.
  portabilidade_oferta: {
    minimo: number;
    maximo: number;
    contratos: { banco: string | null; minimo: number; maximo: number }[];
  } | null;
  // O contrato novo do C6 (decisão 0026), desde a oferta. Convênio e produto
  // são códigos do banco, sem nome.
  contrato_novo: {
    situacao: string;
    valor: string;
    valor_parcela: string;
    numero_parcelas: number;
    taxa_mensal: string;
    convenio: string;
    produto: string;
  } | null;
  // A última consulta ao iCred (decisão 0027); o pacote vem sem comissão.
  icred: {
    estado: string;
    // Do motor, ou `OUTRO_TITULAR` quando a conversa descartou a consulta.
    situacao: string | null;
    contratos: {
      tipo: string;
      banco: string | null;
      taxa: string;
      prazo: number;
      parcela: string;
      liberado: string;
    }[];
    valido_ate: string | null;
    atualizada_em: string;
  } | null;
  proposta: {
    id: number;
    status: string | null;
    estado_envio: string;
    valor_parcela: string;
    numero_parcelas: number;
    atualizada_em: string;
    // A simulação que o cliente aceitou, guardada na proposta; nula nas antigas.
    condicoes: Ficha["oferta"];
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

// Consultas da Granatech gastas por dia no mês corrente (aba Operação).
export interface CotaPorDia {
  de: string;
  ate: string;
  teto_diario: number;
  teto_mensal: number;
  dias: { dia: string; usadas: number }[];
}

// Produto em operação e as regras vigentes dele (aba Operação).
export interface Produto {
  id: string;
  nome: string;
  banco: { id: string; nome: string };
  situacao: string;
  grupos: { titulo: string; itens: { rotulo: string; valor: string }[] }[];
}

export interface Usuario {
  id: string;
  nome: string;
  email: string;
  perfil: Perfil;
  estado: EstadoMembro;
}

export type EstadoMembro = "disponivel" | "ausente" | "fora";

export interface AcaoDoMembro {
  acao: string;
  quando: string;
  conversa_id: string | null;
}

// Um membro da equipe (aba Membros, decisão 0023). O servidor decide o que
// manda conforme o `nivel` de quem pede: do colega só vem o primeiro bloco.
export interface Membro {
  id: string;
  nome: string;
  foto: string | null;
  cargo: string | null;
  perfil: Perfil;
  estado: EstadoMembro;
  conversas_assumidas: number;
  voce: boolean;
  nivel: "colega" | "proprio" | "gestor";
  // A própria pessoa e o gestor. O telefone vem mascarado.
  email?: string;
  telefone?: string | null;
  pode_editar_agente?: boolean;
  pode_testar_fluxos?: boolean;
  ultimo_acesso_em?: string | null;
  criado_em?: string;
  // Só o gestor.
  situacao?: "ativo" | "bloqueado" | "desativado";
  bloqueado_ate?: string | null;
  tentativas_falhas?: number;
  observacao?: string | null;
  // Senha definida pelo gestor que a pessoa ainda não trocou (decisão 0030).
  trocar_senha?: boolean;
  // Só na página do membro (`/membros/{id}`).
  atividade?: { mensagens: number; assumidas: number; devolvidas: number; transferidas: number };
  acoes?: AcaoDoMembro[];
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
  // `rotulo` vem de SATURDAY_WHATSAPP_ROTULOS; nulo quando o número não tem nome.
  // `numero_exibido` (mascarado) e `qualidade` são lidos na Meta; se ela não
  // responde, vêm vazios e `erro` diz por quê.
  meta: {
    phone_number_id: string;
    rotulo: string | null;
    numero_exibido: string;
    qualidade: "GREEN" | "YELLOW" | "RED" | "NA" | string;
    erro: string | null;
  }[];
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

// Página Integrações (decisão 0035): token do APP MEX no proxy da Granatech.
export type EscopoIntegracao = "leitura" | "revelar" | "acoes" | "operacoes" | "homologacao";

export interface Integracao {
  id: string;
  nome: string;
  escopos: EscopoIntegracao[];
  criada_por: string | null;
  criada_em: string;
  revogada_em: string | null;
  ultimo_uso_em: string | null;
  webhook_url: string | null;
  tem_segredo: boolean;
}

export interface EntregaIntegracao {
  id: number;
  tipo: "consulta" | "proposta";
  status: string | null;
  situacao: "entregue" | "pendente" | "desistiu";
  tentativas: number;
  criada_em: string;
  entregue_em: string | null;
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
  // Vazios nos turnos gravados antes da aba Agente.
  duracao_ms: number | null;
  erro: string | null;
}

// Estado técnico depois de um nó da execução, lido dos checkpoints. Texto do
// cliente e dados pessoais nunca vêm: `ocultos` traz só o nome do que mudou.
export interface PassoDoNo {
  no: string;
  campos: { campo: string; valor: string | number | boolean | null; mudou: boolean }[];
  ocultos: string[];
}

export interface Execucao extends Turno {
  conversa_id: string;
  telefone: string | null;
  canal: string;
  membro: string | null;
}

export interface Execucoes {
  execucoes: Execucao[];
  tem_mais: boolean;
}

export type SituacaoExecucao = "todas" | "erro" | "handoff";

export interface NoDoGrafo {
  id: string;
  descricao: string | null;
  modelo: { variavel: string; valor: string } | null;
  passagens_24h: number;
}

export interface Grafo {
  nos: NoDoGrafo[];
  arestas: { de: string; para: string; condicional: boolean }[];
}

export type PapelModelo = "jev" | "llm" | "visao" | "transcricao" | "embeddings";

export interface FonteConhecimento {
  id: string;
  titulo: string;
  tipo: "texto" | "pdf" | "markdown" | "txt";
  arquivo_nome: string | null;
  tamanho: number;
  status: "pendente" | "indexando" | "pronta" | "erro";
  erro: string | null;
  trechos: number;
  modelo: string | null;
  desatualizada: boolean;
  autor: string | null;
  criada_em: string;
  atualizada_em: string;
  indexada_em: string | null;
  editavel: boolean;
}

export interface BaseConhecimento {
  fontes: FonteConhecimento[];
  modelo_embeddings: string;
  pode_editar: boolean;
}

export interface ModeloDoCatalogo {
  id: string;
  nome: string;
  contexto: number | null;
  max_saida: number | null;
  entrada: string[];
  saida: string[];
  // US$ por milhão de tokens (imagem: por milhão de unidades, como a fonte cobra).
  preco_entrada: number | null;
  preco_saida: number | null;
  preco_imagem: number | null;
  parametros: string[];
}

export interface VersaoAgente {
  versao: number;
  modelos: Partial<Record<PapelModelo, string>>;
  nota: string | null;
  restaurada_de: number | null;
  autor: string | null;
  criada_em: string;
}

export interface ModelosAgente {
  vigente: VersaoAgente | null;
  papeis: {
    papel: PapelModelo;
    rotulo: string;
    no: string | null;
    do_catalogo: boolean;
    exige_entrada: string | null;
    // "text" (conversa) ou "embeddings": separa as listas do catálogo por etapa.
    saida: string;
    modelo: string;
    origem: "versao" | "ambiente";
    variavel: string;
  }[];
  catalogo: { fonte: string; buscado_em: string | null; modelos: ModeloDoCatalogo[] };
  transcricao_provedor: string;
  latencia: Record<string, { media_ms: number; p95_ms: number; chamadas: number }>;
  latencia_dias: number;
  em_andamento: number;
  pode_editar: boolean;
  pode_testar: boolean;
}

export interface ResultadoTeste {
  ok: boolean;
  erro: string | null;
  resposta: string | null;
  detalhe: Record<string, unknown> | null;
  latencia_ms: number;
  custo_usd: number | null;
  tokens_entrada: number | null;
  tokens_saida: number | null;
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

// Funil da aba Operação (decisão 0031). Conta e taxa vêm do servidor; a célula
// nula é etapa que o produto não tem ("não se aplica"), não zero.
export type PeriodoDoFunil = "hoje" | "7d" | "30d" | "mes";

export interface Funil {
  periodo: PeriodoDoFunil;
  de: string;
  ate: string;
  iniciadas: number;
  sem_publico: number;
  etapas: { id: string; rotulo: string }[];
  produtos: {
    id: string;
    nome: string;
    celulas: ({ conversas: number; taxa: number | null } | null)[];
  }[];
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

// Correção da ficha pelo painel: só os campos que mudaram.
export interface EdicaoFicha {
  nome?: string;
  nascimento?: string;
  sexo?: "F" | "M";
  email?: string;
  celular?: string;
  cpf?: string;
  conta?: ContaNova & { banco_nome?: string };
}

export interface RespostaRapida {
  id: number;
  atalho: string;
  texto: string;
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
  readonly status: number;
  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.status = status;
  }
}

/** O que mostrar na tela quando uma chamada falha. A recusa do servidor já vem
 *  em português; falha de rede chega como `TypeError: Failed to fetch` — que não
 *  vai para a tela do atendente. */
export function mensagemDeFalha(erro: unknown, acao?: string): string {
  if (erro instanceof ErroApi) return erro.message;
  return acao
    ? `Não consegui ${acao}: o servidor não respondeu. Confira a conexão e tente de novo.`
    : "Não consegui falar com o servidor. Confira a conexão e tente de novo.";
}

let csrf = "";

export function guardarCsrf(token: string): void {
  csrf = token;
}

// Avisado quando a API responde 401 com alguém logado: a sessão de 8 h venceu
// ou foi encerrada. O App escuta e volta para o login.
export const SESSAO_EXPIRADA = "painel:sessao-expirada";

// Sem resposta do servidor (rede caiu, API fora): status 0 e texto em português,
// em vez do "Failed to fetch" do navegador.
async function buscar(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ErroApi(0, "Sem conexão com o servidor. Confira a internet e tente de novo.");
  }
}

// Quando a API não diz o motivo (proxy, timeout, erro sem JSON).
const PADRAO: Record<number, string> = {
  401: "Sua sessão expirou. Entre de novo.",
  403: "Você não tem permissão para isso.",
  404: "Não encontrado: pode ter sido apagado ou o link está errado.",
  409: "Alguém mudou isso antes de você. Recarregue e confira.",
  413: "Arquivo grande demais.",
  422: "O servidor recusou o pedido: algum dado veio em formato errado.",
  429: "Muitas tentativas seguidas. Espere um pouco e tente de novo.",
};

function textoPadrao(status: number): string {
  if (PADRAO[status]) return PADRAO[status];
  if (status >= 500) return "O servidor falhou ao responder. Tente de novo em instantes.";
  return `Não deu certo (erro ${status}).`;
}

// Textos que o FastAPI/Starlette põem sozinhos, em inglês (rota que não existe etc.).
const PADROES_DO_STARLETTE = new Set(["Not Found", "Method Not Allowed", "Not authenticated", "Forbidden"]);

// Texto do erro para a tela. A validação do pydantic responde uma lista; só os
// nossos validadores (`value_error`) falam português, as mensagens prontas do
// pydantic vêm em inglês e dão lugar ao texto padrão do status.
export function detalheDoErro(status: number, corpo: unknown): string {
  const detail = (corpo as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail && !PADROES_DO_STARLETTE.has(detail)) return detail;
  if (Array.isArray(detail)) {
    const nossos = detail
      .filter((e: { type?: string }) => e?.type === "value_error")
      .map((e: { msg?: string }) => (e.msg ?? "").replace(/^Value error, /, ""))
      .filter(Boolean);
    if (nossos.length > 0) return nossos.join("; ");
  }
  return textoPadrao(status);
}

async function chamar<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
  const cabecalhos: Record<string, string> = {};
  if (metodo !== "GET") cabecalhos["X-CSRF-Token"] = csrf;
  if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  return responder<T>(
    await buscar(`/admin${caminho}`, {
      method: metodo,
      headers: cabecalhos,
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
      credentials: "same-origin",
    }),
  );
}

async function responder<T>(resposta: Response): Promise<T> {
  if (!resposta.ok) {
    // O login responde 401 a senha errada: ali não é sessão vencida.
    if (resposta.status === 401 && csrf && !resposta.url.endsWith("/admin/login"))
      window.dispatchEvent(new Event(SESSAO_EXPIRADA));
    let corpo: unknown = null;
    try {
      corpo = await resposta.json();
    } catch {
      // corpo sem JSON: fica o texto padrão do status
    }
    throw new ErroApi(resposta.status, detalheDoErro(resposta.status, corpo));
  }
  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

// Anexo do painel: o arquivo vai cru no corpo, com o MIME no Content-Type
// (sem multipart nem base64). A legenda segue o texto do campo.
export function enviarAnexo(id: string, arquivo: Blob, nome: string, legenda: string) {
  const params = new URLSearchParams({ nome, legenda });
  return buscar(`/admin/conversas/${id}/anexos?${params}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf, "Content-Type": arquivo.type || "application/octet-stream" },
    body: arquivo,
    credentials: "same-origin",
  }).then((r) => responder<{ mensagem_id: number }>(r));
}

// Foto do perfil: arquivo cru no corpo, como o anexo. Devolve o "eu" atualizado.
export function enviarFoto(arquivo: File) {
  return buscar("/admin/eu/foto", {
    method: "PUT",
    headers: { "X-CSRF-Token": csrf, "Content-Type": arquivo.type || "application/octet-stream" },
    body: arquivo,
    credentials: "same-origin",
  }).then((r) => responder<Eu>(r));
}

// Fonte da base de conhecimento: arquivo cru no corpo, como o anexo.
export function enviarFonte(arquivo: File, titulo: string) {
  const params = new URLSearchParams({ titulo, nome: arquivo.name });
  return buscar(`/admin/agente/conhecimento/arquivo?${params}`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf, "Content-Type": arquivo.type || "application/octet-stream" },
    body: arquivo,
    credentials: "same-origin",
  }).then((r) => responder<{ id: string }>(r));
}

// Espelha `painel/midia.py`: tipos aceitos e limite de cada um, em bytes.
const MB = 1024 * 1024;
export const ANEXOS_ACEITOS: Record<string, number> = {
  "image/jpeg": 5 * MB,
  "image/png": 5 * MB,
  "application/pdf": 16 * MB,
  "audio/webm": 16 * MB,
  "audio/ogg": 16 * MB,
  "audio/mp4": 16 * MB,
  "audio/mpeg": 16 * MB,
};

export const api = {
  entrar: (email: string, senha: string) => chamar<Eu>("POST", "/login", { email, senha }),
  sair: () => chamar<void>("POST", "/logout"),
  eu: () => chamar<Eu>("GET", "/eu"),
  trocarSenha: (atual: string, nova: string) => chamar<void>("POST", "/eu/senha", { atual, nova }),
  usuarios: () => chamar<Usuario[]>("GET", "/usuarios"),
  conversas: (fila: string, busca: string) => {
    const params = new URLSearchParams();
    if (fila) params.set("fila", fila);
    if (busca) params.set("busca", busca);
    return chamar<Resumo[]>("GET", `/conversas?${params}`);
  },
  contagens: () => chamar<Contagens>("GET", "/conversas/contagens"),
  conversa: (id: string) => chamar<Detalhe>("GET", `/conversas/${id}`),
  assumir: (id: string) => chamar<void>("POST", `/conversas/${id}/assumir`),
  devolver: (id: string) => chamar<void>("POST", `/conversas/${id}/devolver`),
  desfazer: (id: string) => chamar<void>("POST", `/conversas/${id}/desfazer`),
  transferir: (id: string, usuario_id: string) =>
    chamar<void>("POST", `/conversas/${id}/transferir`, { usuario_id }),
  enviar: (id: string, envio: { texto: string } | { modelo: string }) =>
    chamar<{ mensagem_id: number }>("POST", `/conversas/${id}/mensagens`, envio),
  ficha: (id: string) => chamar<Ficha>("GET", `/conversas/${id}/ficha`),
  editarFicha: (id: string, edicao: EdicaoFicha) =>
    chamar<void>("PATCH", `/conversas/${id}/ficha`, edicao),
  respostas: () => chamar<RespostaRapida[]>("GET", "/respostas-rapidas"),
  criarResposta: (r: Omit<RespostaRapida, "id">) =>
    chamar<RespostaRapida>("POST", "/respostas-rapidas", r),
  editarResposta: (id: number, r: Omit<RespostaRapida, "id">) =>
    chamar<RespostaRapida>("PATCH", `/respostas-rapidas/${id}`, r),
  apagarResposta: (id: number) => chamar<void>("DELETE", `/respostas-rapidas/${id}`),
  revelar: (id: string, campo: CampoSensivel) =>
    chamar<{ campo: CampoSensivel; valor: string }>("POST", `/conversas/${id}/revelar`, { campo }),
  alertas: () => chamar<Alerta[]>("GET", "/alertas"),
  resolverAlerta: (id: number) => chamar<void>("POST", `/alertas/${id}/resolver`),
  cota: () => chamar<Cota>("GET", "/cota"),
  canais: () => chamar<Canais>("GET", "/canais"),
  atualizarPerfil: (nome: string, telefone: string) =>
    chamar<Eu>("PATCH", "/eu", { nome, telefone: telefone || null }),
  removerFoto: () => chamar<Eu>("DELETE", "/eu/foto"),
  marcarDisponibilidade: (disponivel: boolean) =>
    chamar<Eu>("PATCH", "/eu/disponibilidade", { disponivel }),
  membros: () => chamar<Membro[]>("GET", "/membros"),
  membro: (id: string) => chamar<Membro>("GET", `/membros/${id}`),
  criarUsuario: (dados: NovoUsuario) => chamar<{ id: string }>("POST", "/gestao/usuarios", dados),
  integracoes: () => chamar<Integracao[]>("GET", "/gestao/integracoes"),
  criarIntegracao: (nome: string, escopos: EscopoIntegracao[]) =>
    chamar<Integracao & { token: string }>("POST", "/gestao/integracoes", { nome, escopos }),
  revogarIntegracao: (id: string) => chamar<void>("POST", `/gestao/integracoes/${id}/revogar`),
  definirWebhook: (id: string, url: string | null) =>
    chamar<void>("PUT", `/gestao/integracoes/${id}/webhook`, { url }),
  gerarSegredo: (id: string) =>
    chamar<{ segredo: string }>("POST", `/gestao/integracoes/${id}/webhook/segredo`),
  entregasIntegracao: (id: string) =>
    chamar<EntregaIntegracao[]>("GET", `/gestao/integracoes/${id}/webhook/entregas`),
  editarUsuario: (
    id: string,
    dados: {
      nome: string;
      email: string;
      perfil: Perfil;
      pode_editar_agente: boolean;
      pode_testar_fluxos: boolean;
      cargo: string;
      observacao: string;
    },
  ) =>
    chamar<void>("PATCH", `/gestao/usuarios/${id}`, dados),
  redefinirSenha: (id: string, senha: string) =>
    chamar<void>("POST", `/gestao/usuarios/${id}/senha`, { senha }),
  desbloquearUsuario: (id: string) => chamar<void>("POST", `/gestao/usuarios/${id}/desbloquear`),
  desativarUsuario: (id: string) =>
    chamar<{ conversas_devolvidas: number }>("POST", `/gestao/usuarios/${id}/desativar`),
  reativarUsuario: (id: string) => chamar<void>("POST", `/gestao/usuarios/${id}/reativar`),
  turnos: (id: string) => chamar<Trilha>("GET", `/conversas/${id}/turnos`),
  custos: () => chamar<Custos>("GET", "/custos"),
  funil: (periodo: PeriodoDoFunil) => chamar<Funil>("GET", `/funil?periodo=${periodo}`),
  cotaPorDia: () => chamar<CotaPorDia>("GET", "/cota/dias"),
  produtos: () => chamar<Produto[]>("GET", "/produtos"),
  grafo: () => chamar<Grafo>("GET", "/agente/grafo"),
  // `passos` nulo: os checkpoints do turno já foram podados pela retenção.
  passos: (turno: number) =>
    chamar<{ passos: PassoDoNo[] | null }>("GET", `/agente/execucoes/${turno}/passos`),
  modelosAgente: () => chamar<ModelosAgente>("GET", "/agente/modelos"),
  atualizarCatalogo: () => chamar<{ modelos: number }>("POST", "/agente/catalogo/atualizar"),
  testarModelo: (papel: PapelModelo, modelo: string, texto: string) =>
    chamar<ResultadoTeste>("POST", "/agente/modelos/testar", { papel, modelo, texto }),
  versoesAgente: () => chamar<VersaoAgente[]>("GET", "/agente/versoes"),
  conhecimento: () => chamar<BaseConhecimento>("GET", "/agente/conhecimento"),
  adicionarTexto: (titulo: string, texto: string) =>
    chamar<{ id: string }>("POST", "/agente/conhecimento/texto", { titulo, texto }),
  editarFonte: (id: string, dados: { titulo?: string; texto?: string }) =>
    chamar<void>("PATCH", `/agente/conhecimento/${id}`, dados),
  reindexarFonte: (id: string) => chamar<void>("POST", `/agente/conhecimento/${id}/reindexar`),
  reindexarTodas: () => chamar<{ fontes: number }>("POST", "/agente/conhecimento/reindexar"),
  removerFonte: (id: string) => chamar<void>("DELETE", `/agente/conhecimento/${id}`),
  salvarVersao: (
    versao_base: number | null,
    modelos: Partial<Record<PapelModelo, string>>,
    nota: string,
  ) => chamar<{ versao: number }>("POST", "/agente/versoes", { versao_base, modelos, nota }),
  restaurarVersao: (versao: number, versao_base: number | null) =>
    chamar<{ versao: number }>("POST", `/agente/versoes/${versao}/restaurar`, { versao_base }),
  execucoes: (filtro: { no?: string; situacao: SituacaoExecucao; antes_de?: number }) => {
    const q = new URLSearchParams({ situacao: filtro.situacao });
    if (filtro.no) q.set("no", filtro.no);
    if (filtro.antes_de) q.set("antes_de", String(filtro.antes_de));
    return chamar<Execucoes>("GET", `/agente/execucoes?${q}`);
  },
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
