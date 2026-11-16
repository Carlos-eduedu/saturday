// O que quem vê pode fazer com a conversa. Espelha o servidor
// (`painel/acoes.py`: `_exigir_dono`, assumir, devolver), que é quem recusa de
// fato; aqui a tela só decide o que oferecer. Sem import em tempo de execução,
// para o teste rodar em Node.

interface DaConversa {
  atendimento: string;
  atendente_id: string | null;
  janela: "aberta" | "fechada" | null;
}

export interface Permissoes {
  // Assumida por quem vê.
  minha: boolean;
  // Da IA ou do handoff, qualquer um; de outro atendente, só o gestor.
  podeAssumir: boolean;
  // Assumir aqui tira a conversa de outro atendente: a tela pede confirmação.
  tomaDeOutro: boolean;
  // Handoff, qualquer um; assumida, o dono ou o gestor.
  podeDevolver: boolean;
  // Ficha e transferência: o dono ou o gestor.
  podeMexer: boolean;
  // Texto e anexo agora: só a janela fechada da Meta barra; canal sem
  // janela (`null`) escreve sempre (decisão 0009).
  janelaAberta: boolean;
}

export function permissoesDa(conversa: DaConversa, eu: { id: string; perfil: string }): Permissoes {
  const gestor = eu.perfil === "gestor";
  const assumida = conversa.atendimento === "assumida";
  const minha = assumida && conversa.atendente_id === eu.id;
  const podeAssumir = !minha && (!assumida || gestor);
  return {
    minha,
    podeAssumir,
    tomaDeOutro: podeAssumir && assumida,
    podeDevolver: conversa.atendimento !== "ia" && (conversa.atendimento === "handoff" || minha || gestor),
    podeMexer: minha || gestor,
    janelaAberta: conversa.janela !== "fechada",
  };
}
