import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useRef, useState } from "react";

// Aviso de "deu certo" que some sozinho, com o desenho do aviso de desfazer.
// Abre como popover: fica na camada de cima, à vista mesmo com um modal aberto.
const NOTIFICACAO_MS = 4000;

export function Notificacao({ texto, aoFechar }: { texto: string; aoFechar: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  // Mouse em cima ou foco de teclado seguram o relógio, como no Desfazer.
  const [seguro, setSeguro] = useState(false);

  useEffect(() => {
    ref.current?.showPopover();
  }, []);
  useEffect(() => {
    if (seguro) return;
    const timer = window.setTimeout(aoFechar, NOTIFICACAO_MS);
    return () => window.clearTimeout(timer);
  }, [texto, seguro, aoFechar]);

  return (
    <div
      ref={ref}
      popover="manual"
      className="aviso-flutuante"
      role="status"
      onPointerEnter={(e) => e.pointerType === "mouse" && setSeguro(true)}
      onPointerLeave={() => setSeguro(false)}
      onFocus={(e) => e.target.matches(":focus-visible") && setSeguro(true)}
      onBlur={() => setSeguro(false)}
    >
      <span title={texto}>{texto}</span>
      <button type="button" className="fechar" aria-label="Fechar aviso" onClick={aoFechar}>
        <HugeiconsIcon icon={Cancel01Icon} size={18} strokeWidth={2} />
      </button>
    </div>
  );
}
