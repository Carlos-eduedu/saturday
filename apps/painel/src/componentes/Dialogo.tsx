import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type ReactNode, useEffect, useId, useRef } from "react";

// Diálogo modal nativo: `showModal` prende o foco, Esc fecha, e o clique no
// fundo também (o <dialog> não tem padding: clicar nele é clicar fora).
export function Dialogo({
  titulo,
  aoFechar,
  rodape,
  children,
}: {
  titulo: string;
  aoFechar: () => void;
  rodape?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const idTitulo = useId();
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const fechar = () => ref.current?.close();

  return (
    <dialog
      ref={ref}
      className="dialogo"
      aria-labelledby={idTitulo}
      onClose={aoFechar}
      onClick={(e) => e.target === ref.current && fechar()}
    >
      <div className="dialogo__corpo">
        <header>
          <h2 id={idTitulo}>{titulo}</h2>
          <button type="button" className="fechar" onClick={fechar} aria-label="Fechar">
            <HugeiconsIcon icon={Cancel01Icon} size={20} strokeWidth={2} />
          </button>
        </header>
        <div className="dialogo__conteudo">{children}</div>
        {rodape && <footer>{rodape}</footer>}
      </div>
    </dialog>
  );
}
