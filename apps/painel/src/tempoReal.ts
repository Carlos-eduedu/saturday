// Um único EventSource por aba. Cada aviso (só tipo e IDs) vira um evento
// `painel` na janela; as telas escutam e buscam de novo o que precisam. Ao
// reconectar, avisos perdidos não voltam: as telas recarregam tudo.

import { useEffect } from "react";

export interface Aviso {
  tipo:
    | "mensagem"
    | "conversa"
    | "alerta"
    | "granatech"
    | "homologacao"
    | "turno"
    | "reconectado";
  conversa?: string;
  alerta?: string;
  rodada?: string;
}

const EVENTO = "painel";

export function iniciarTempoReal(): () => void {
  const fonte = new EventSource("/admin/eventos");
  let jaAbriu = false;
  fonte.onopen = () => {
    if (jaAbriu) emitir({ tipo: "reconectado" });
    jaAbriu = true;
  };
  fonte.onmessage = (evento) => {
    // Um aviso malformado não derruba os seguintes.
    try {
      emitir(JSON.parse(evento.data) as Aviso);
    } catch {
      // ignora
    }
  };
  return () => fonte.close();
}

function emitir(aviso: Aviso): void {
  window.dispatchEvent(new CustomEvent<Aviso>(EVENTO, { detail: aviso }));
}

export function useAvisos(aoAvisar: (aviso: Aviso) => void): void {
  useEffect(() => {
    const ouvir = (evento: Event) => aoAvisar((evento as CustomEvent<Aviso>).detail);
    window.addEventListener(EVENTO, ouvir);
    return () => window.removeEventListener(EVENTO, ouvir);
  }, [aoAvisar]);
}
