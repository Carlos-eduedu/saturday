import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { Dialogo } from "./Dialogo";

// Confirmação de ação destrutiva no Dialogo da casa, no lugar do
// window.confirm (que não segue o tema nem o layout do celular). Devolve uma
// promessa: `if (!(await confirmar({...}))) return;`.
export interface Pedido {
  titulo: string;
  texto: ReactNode;
  // Verbo do botão que confirma ("Apagar", "Desativar"…).
  acao: string;
  // Botão vermelho: a ação apaga, desliga ou tira algo de alguém.
  perigo?: boolean;
}

type Confirmar = (pedido: Pedido) => Promise<boolean>;

const Contexto = createContext<Confirmar>(async () => false);
export const useConfirmar = () => useContext(Contexto);

export function ConfirmarProvider({ children }: { children: ReactNode }) {
  const [aberto, setAberto] = useState<(Pedido & { responder: (ok: boolean) => void }) | null>(
    null,
  );
  const confirmar = useCallback<Confirmar>(
    (pedido) =>
      new Promise((resolver) => {
        setAberto({ ...pedido, responder: resolver });
      }),
    [],
  );
  // A promessa só resolve uma vez: Esc, fundo ou "Voltar" depois do botão não mudam nada.
  const responder = (ok: boolean) => {
    aberto?.responder(ok);
    setAberto(null);
  };

  return (
    <Contexto.Provider value={confirmar}>
      {children}
      {aberto && (
        <Dialogo
          titulo={aberto.titulo}
          aoFechar={() => responder(false)}
          rodape={
            <>
              <button type="button" onClick={() => responder(false)}>
                Voltar
              </button>
              <button
                type="button"
                className={aberto.perigo ? "perigo" : "principal"}
                onClick={() => responder(true)}
              >
                {aberto.acao}
              </button>
            </>
          }
        >
          <p>{aberto.texto}</p>
        </Dialogo>
      )}
    </Contexto.Provider>
  );
}
