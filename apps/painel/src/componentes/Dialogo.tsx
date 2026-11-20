import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type ReactNode, useEffect, useId, useRef } from "react";

// Diálogo modal nativo: `showModal` prende o foco, Esc fecha, e o clique no
// fundo também (o <dialog> não tem padding: clicar nele é clicar fora).
export function Dialogo({
  titulo,
  aoFechar,
  rodape,
  largo = false,
  classe,
  travado = false,
  children,
}: {
  titulo: ReactNode;
  aoFechar: () => void;
  rodape?: ReactNode;
  // Conteúdo extenso (rodada da homologação): 46rem em vez de 36rem.
  largo?: boolean;
  // Variação própria de quem usa (o grafo ocupa quase a tela toda).
  classe?: string;
  // Valor que aparece uma vez (token, segredo): Esc e clique fora não fecham.
  travado?: boolean;
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
      className={["dialogo", largo && "dialogo--largo", classe].filter(Boolean).join(" ")}
      aria-labelledby={idTitulo}
      // O detalhe do nó abre dentro do modal do grafo: o `close` dele chega
      // aqui pela árvore do React e não pode fechar este.
      onClose={(e) => e.target === ref.current && aoFechar()}
      onCancel={(e) => travado && e.preventDefault()}
      onClick={(e) => !travado && e.target === ref.current && fechar()}
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
