import { type KeyboardEvent, useId, useRef } from "react";

// Abas sublinhadas, o único estilo de aba de página do painel (Agente,
// Granatech, conversa no celular). Setas, Home e End andam entre as abas e já
// trocam o conteúdo; só a aba atual entra no Tab. Quem usa põe o conteúdo num
// `role="tabpanel"` com `id={painel}` e `aria-labelledby={idAba(painel, valor)}`.
export const idAba = (painel: string, valor: string) => `${painel}-aba-${valor}`;

export function Abas<T extends string>({
  rotulo,
  opcoes,
  valor,
  mudar,
  painel,
}: {
  rotulo: string;
  opcoes: [T, string][];
  valor: T;
  mudar: (v: T) => void;
  painel?: string;
}) {
  const reserva = useId();
  const base = painel ?? reserva;
  const lista = useRef<HTMLDivElement>(null);

  function teclar(e: KeyboardEvent) {
    const atual = opcoes.findIndex(([v]) => v === valor);
    const destino = {
      ArrowRight: (atual + 1) % opcoes.length,
      ArrowLeft: (atual - 1 + opcoes.length) % opcoes.length,
      Home: 0,
      End: opcoes.length - 1,
    }[e.key];
    if (destino === undefined) return;
    const opcao = opcoes[destino];
    if (!opcao) return;
    e.preventDefault();
    mudar(opcao[0]);
    lista.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[destino]?.focus();
  }

  return (
    <div ref={lista} role="tablist" aria-label={rotulo} className="abas-laterais" onKeyDown={teclar}>
      {opcoes.map(([v, texto]) => (
        <button
          key={v}
          id={idAba(base, v)}
          type="button"
          role="tab"
          aria-selected={valor === v}
          aria-controls={painel}
          tabIndex={valor === v ? 0 : -1}
          className={valor === v ? "ativo" : ""}
          onClick={() => mudar(v)}
        >
          {texto}
        </button>
      ))}
    </div>
  );
}
