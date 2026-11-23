// Textos da aba Membros: o estado de uma pessoa e o nome de cada ação da
// auditoria. Sem React, para o teste rodar com `npm run teste`.

export const ROTULO_PERFIL = { atendente: "Atendente", gestor: "Gestor" } as const;

export const ROTULO_ESTADO = {
  disponivel: "Disponível",
  ausente: "Ausente",
  fora: "Fora do painel",
} as const;

const ACOES: Record<string, string> = {
  assumir: "Assumiu a conversa",
  devolver: "Devolveu a conversa à IA",
  desfazer: "Desfez a última ação",
  transferir: "Transferiu a conversa",
  enviar_mensagem: "Enviou uma mensagem",
  enviar_anexo: "Enviou um anexo",
  "conversa:editar_ficha": "Editou a ficha do cliente",
  resolver_alerta: "Resolveu um alerta",
  exportar: "Exportou uma conversa",
  ver_sem_mascara: "Abriu a ficha de um cliente sem máscara",
  perfil_editar: "Editou o próprio perfil",
  perfil_foto: "Trocou a própria foto",
  perfil_foto_remover: "Removeu a própria foto",
  perfil_disponibilidade: "Mudou a disponibilidade",
  granatech_reenviar_link: "Reenviou um link da Granatech",
  integracao_criar: "Criou um token de integração",
  integracao_revogar: "Revogou um token de integração",
  integracao_webhook: "Mudou o webhook de uma integração",
  integracao_segredo: "Gerou o segredo do webhook de uma integração",
  usuario_criar: "Adicionou um membro",
  usuario_editar: "Editou um membro",
  usuario_senha: "Redefiniu a senha de um membro",
  usuario_senha_propria: "Trocou a própria senha",
  usuario_desbloquear: "Desbloqueou um membro",
  usuario_desativar: "Desativou um membro",
  usuario_reativar: "Reativou um membro",
};

// Famílias com muitas variações: o nome da família basta para o gestor.
const FAMILIAS: [string, string][] = [
  ["canal_", "Mexeu nos canais"],
  ["conhecimento_", "Editou a base de conhecimento"],
  ["agente_", "Editou o agente"],
  ["resposta_rapida:", "Editou as respostas rápidas"],
  ["granatech", "Agiu numa consulta ou proposta da Granatech"],
];

const DADOS: Record<string, string> = {
  cpf: "o CPF",
  telefone: "o telefone",
  email: "o e-mail",
  nascimento: "o nascimento",
};

export function rotuloDaAcao(acao: string): string {
  if (acao.startsWith("revelar:")) {
    const campo = acao.slice("revelar:".length);
    return `Revelou ${DADOS[campo] ?? campo} de um cliente`;
  }
  return ACOES[acao] ?? FAMILIAS.find(([prefixo]) => acao.startsWith(prefixo))?.[1] ?? acao;
}

// A regra da senha é do servidor (12 ou mais); aqui só o tamanho, para o campo.
export const SENHA_MINIMA = 12;

/** Por que a troca da própria senha nem sai da tela; vazio quando pode ir. */
export function recusaDaSenhaNova(atual: string, nova: string, repete: string): string {
  if (nova.length < SENHA_MINIMA) return `A senha nova precisa de pelo menos ${SENHA_MINIMA} caracteres.`;
  if (nova !== repete) return "A senha nova e a repetição não conferem.";
  if (nova === atual) return "A senha nova precisa ser diferente da atual.";
  return "";
}

export const conversas = (n: number) => (n === 1 ? "1 conversa" : `${n} conversas`);
