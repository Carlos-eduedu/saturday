// Um dado do servidor que se mantém fresco: carrega, recarrega com os avisos
// do tempo real e descarta resposta velha. Sem React e sem import em tempo de
// execução, para o teste rodar em Node; quem liga às telas é `useRecurso.ts`.

import type { Aviso } from "./tempoReal";

export interface EstadoDoRecurso<T> {
  dado: T | null;
  // De qual chave é o dado: com `manter`, pode ser a anterior à atual.
  chaveDoDado: string | null;
  // Erro bruto da última carga; some na carga seguinte que der certo.
  falha: unknown;
  chaveDaFalha: string | null;
}

const VAZIO: EstadoDoRecurso<never> = { dado: null, chaveDoDado: null, falha: null, chaveDaFalha: null };

export class Recurso<T> {
  private estado: EstadoDoRecurso<T> = VAZIO;
  private chave: string | null = null;
  private buscar: (() => Promise<T>) | null = null;
  private ultimoPedido = 0;
  private readonly ouvintes = new Set<() => void>();
  private readonly manter: boolean;

  // `manter`: ao trocar a chave, o dado antigo fica até o novo chegar.
  constructor(manter = false) {
    this.manter = manter;
  }

  ler = (): EstadoDoRecurso<T> => this.estado;

  assinar = (ouvinte: () => void): (() => void) => {
    this.ouvintes.add(ouvinte);
    return () => this.ouvintes.delete(ouvinte);
  };

  // Diz o que buscar. A chave muda quando muda o que se busca (id, filtro, aba).
  apontar(chave: string, buscar: () => Promise<T>): void {
    if (chave !== this.chave && !this.manter) this.mudar(VAZIO);
    this.chave = chave;
    this.buscar = buscar;
    this.carregar();
  }

  // Só a resposta do último pedido vale: digitação e avisos chegam em rajada,
  // e uma resposta velha cobriria a nova.
  carregar = (): void => {
    const { chave, buscar } = this;
    if (chave === null || buscar === null) return;
    const pedido = ++this.ultimoPedido;
    buscar().then(
      (dado) => {
        if (pedido !== this.ultimoPedido) return;
        this.mudar({ dado, chaveDoDado: chave, falha: null, chaveDaFalha: null });
      },
      (falha: unknown) => {
        if (pedido !== this.ultimoPedido) return;
        // Falha ao recarregar mantém à vista o que já estava.
        this.mudar({ ...this.estado, falha, chaveDaFalha: chave });
      },
    );
  };

  // Ao reconectar, avisos perdidos não voltam: recarrega sempre.
  avisar(aviso: Aviso, recarrega?: (aviso: Aviso) => boolean): void {
    if (aviso.tipo === "reconectado" || recarrega?.(aviso)) this.carregar();
  }

  private mudar(estado: EstadoDoRecurso<T>): void {
    this.estado = estado;
    for (const ouvinte of this.ouvintes) ouvinte();
  }
}
