// A ação de um botão da tela: uma por vez, com aviso ou erro no fim e a tela
// recarregada. Sem React, para o teste rodar com `node`; `useAcao.ts` liga à tela.

export interface Saidas {
  erro: (texto: string) => void;
  aviso: (texto: string) => void;
  // Roda no fim, com a ação certa ou não: a tela busca o estado de agora.
  depois: () => void;
  falha: (erro: unknown) => string;
  // Texto mostrado enquanto a ação roda.
  andamento?: string;
}

export function criarAgir(saidas: Saidas) {
  let ocupado = false;
  // Devolve se a ação deu certo; a que chega com outra em andamento é ignorada.
  return async function agir<T>(
    acao: () => Promise<T>,
    feito: string | ((resultado: T) => string) = "",
  ): Promise<boolean> {
    if (ocupado) return false;
    ocupado = true;
    saidas.erro("");
    saidas.aviso(saidas.andamento ?? "");
    try {
      const resultado = await acao();
      saidas.aviso(typeof feito === "string" ? feito : feito(resultado));
      return true;
    } catch (e) {
      saidas.aviso("");
      saidas.erro(saidas.falha(e));
      return false;
    } finally {
      ocupado = false;
      saidas.depois();
    }
  };
}
