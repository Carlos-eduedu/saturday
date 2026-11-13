import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { api } from "../api";

// Assumir e devolver valem na hora, na lista e na conversa; por 5 s o aviso
// deixa desfazer, e a API devolve a conversa ao estado de antes.
const DESFAZER_MS = 5000;

interface Aviso {
  id: string;
  texto: string;
  // Recarrega quem mostrou a ação, mesmo com o tempo real fora do ar.
  depois: () => void;
  falhou?: boolean;
}

const Contexto = createContext<(aviso: Aviso) => void>(() => undefined);
export const useAvisoDesfazer = () => useContext(Contexto);

export const textoDoAviso = (acao: "assumir" | "devolver", conversa: string) =>
  acao === "assumir" ? `Você assumiu ${conversa}` : `Você devolveu ${conversa} para a IA`;

export const confirmarTomada = (dono: string) =>
  window.confirm(
    `Assumir a conversa que está com ${dono}? Essa pessoa deixa de ser a dona dela.`,
  );

export function AvisoDesfazer({ children }: { children: ReactNode }) {
  const [aviso, setAviso] = useState<Aviso | null>(null);
  // Mouse em cima ou foco de teclado seguram o relógio: 5 s não bastam no
  // teclado. Toque não segura: no celular o pointerleave não chega e o aviso
  // ficava preso sobre o campo de texto.
  const [seguro, setSeguro] = useState(false);

  useEffect(() => {
    if (!aviso || seguro) return;
    const timer = window.setTimeout(() => setAviso(null), DESFAZER_MS);
    return () => window.clearTimeout(timer);
  }, [aviso, seguro]);

  async function desfazer(atual: Aviso) {
    setSeguro(false);
    try {
      await api.desfazer(atual.id);
      setAviso(null);
    } catch (e) {
      const motivo = e instanceof Error ? e.message : "tente de novo";
      setAviso({ ...atual, texto: `Não deu para desfazer: ${motivo}`, falhou: true });
    }
    atual.depois();
  }

  return (
    <Contexto.Provider value={setAviso}>
      {children}
      {aviso && (
        <div
          className="aviso-flutuante"
          role={aviso.falhou ? "alert" : "status"}
          onPointerEnter={(e) => e.pointerType === "mouse" && setSeguro(true)}
          onPointerLeave={() => setSeguro(false)}
          onFocus={(e) => e.target.matches(":focus-visible") && setSeguro(true)}
          onBlur={() => setSeguro(false)}
        >
          <span title={aviso.texto}>{aviso.texto}</span>
          {!aviso.falhou && (
            <button type="button" onClick={() => desfazer(aviso)}>
              Desfazer
            </button>
          )}
          <button
            type="button"
            className="fechar"
            aria-label="Fechar aviso"
            onClick={() => {
              setSeguro(false);
              setAviso(null);
            }}
          >
            ×
          </button>
        </div>
      )}
    </Contexto.Provider>
  );
}
