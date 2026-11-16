// Liga `criarAgir` (acao.ts) à tela: a tela diz como recarregar e desenha o
// erro e o aviso do jeito dela.

import { useEffect, useRef, useState } from "react";
import { criarAgir } from "./acao";
import { mensagemDeFalha } from "./api";

export function useAcao(carregar: () => void, andamento?: string) {
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  // `carregar` muda a cada render; a ação usa sempre o de agora.
  const depois = useRef(carregar);
  useEffect(() => {
    depois.current = carregar;
  });
  const [agir] = useState(() =>
    criarAgir({
      erro: setErro,
      aviso: setAviso,
      depois: () => depois.current(),
      falha: (e) => mensagemDeFalha(e),
      andamento,
    }),
  );
  // `setErro` e `setAviso` saem porque a falha de carga usa o mesmo lugar na tela.
  return { agir, erro, aviso, setErro, setAviso };
}
