// Liga um `Recurso` (recurso.ts) à tela: a tela diz o que buscar e quais avisos
// recarregam; carga, erro, reconexão e descarte de resposta velha ficam lá.

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Recurso } from "./recurso";
import { type Aviso, ouvirAvisos } from "./tempoReal";

export function useRecurso<T>(
  // Muda quando muda o que se busca (id, filtro, aba): dispara carga nova.
  chave: string,
  buscar: () => Promise<T>,
  opcoes: {
    // Avisos que recarregam, além da reconexão, que sempre recarrega.
    recarrega?: (aviso: Aviso) => boolean;
    // Ao trocar a chave, o dado antigo fica à vista até o novo chegar.
    manter?: boolean;
  } = {},
) {
  const manter = opcoes.manter ?? false;
  const [recurso] = useState(() => new Recurso<T>(manter));
  const estado = useSyncExternalStore(recurso.assinar, recurso.ler);

  // As funções mudam a cada render; só a chave decide quando buscar de novo.
  const atual = useRef({ buscar, recarrega: opcoes.recarrega });
  useEffect(() => {
    atual.current = { buscar, recarrega: opcoes.recarrega };
  });
  useEffect(() => recurso.apontar(chave, () => atual.current.buscar()), [recurso, chave]);
  useEffect(
    () => ouvirAvisos((aviso) => recurso.avisar(aviso, atual.current.recarrega)),
    [recurso],
  );

  // Entre o render e a carga da chave nova, o que é da anterior não aparece.
  const doAtual = manter || estado.chaveDoDado === chave;
  return {
    dado: doAtual ? estado.dado : null,
    chaveDoDado: doAtual ? estado.chaveDoDado : null,
    falha: estado.chaveDaFalha === chave ? estado.falha : null,
    carregar: useCallback(() => recurso.carregar(), [recurso]),
  };
}
