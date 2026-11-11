import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type Eu, type Resumo } from "../api";
import { useAvisos } from "../tempoReal";

const FILAS = [
  { valor: "", rotulo: "Todas" },
  { valor: "ia", rotulo: "Com a IA" },
  { valor: "handoff", rotulo: "Aguardando humano" },
  { valor: "assumida", rotulo: "Com humano" },
  { valor: "minhas", rotulo: "Minhas" },
];

export const ROTULO_ATENDIMENTO = { ia: "IA", handoff: "Handoff", assumida: "Assumida" } as const;

export function Inbox({ eu }: { eu: Eu }) {
  const [fila, setFila] = useState("handoff");
  const [busca, setBusca] = useState("");
  const [conversas, setConversas] = useState<Resumo[]>([]);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    api
      .conversas(fila, busca)
      .then((lista) => {
        setConversas(lista);
        setErro("");
      })
      .catch((e: Error) => setErro(e.message));
  }, [fila, busca]);

  useEffect(carregar, [carregar]);
  useAvisos(carregar);

  return (
    <section>
      <div className="filtros">
        <div role="tablist" aria-label="Filas">
          {FILAS.map((f) => (
            <button
              key={f.valor}
              type="button"
              role="tab"
              aria-selected={fila === f.valor}
              className={fila === f.valor ? "ativo" : ""}
              onClick={() => setFila(f.valor)}
            >
              {f.rotulo}
            </button>
          ))}
        </div>
        <label>
          Buscar telefone
          <input
            type="search"
            inputMode="numeric"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </label>
      </div>
      {erro && <p className="erro">{erro}</p>}
      {conversas.length === 0 ? (
        <p className="vazio">Nenhuma conversa nesta fila.</p>
      ) : (
        <ul className="inbox">
          {conversas.map((c) => (
            <li key={c.id} className={c.nao_lida ? "nao-lida" : ""}>
              <Link to={`/conversas/${c.id}`}>
                <span className="telefone">{c.telefone ?? c.canal}</span>
                <span className={`selo selo-${c.atendimento}`}>
                  {ROTULO_ATENDIMENTO[c.atendimento]}
                  {c.atendente_id === eu.id ? " (você)" : ""}
                </span>
                {c.canal === "whatsapp" && (
                  <span className={c.janela_aberta ? "janela aberta" : "janela fechada"}>
                    {c.janela_aberta ? "janela aberta" : "janela fechada"}
                  </span>
                )}
                {c.nao_lida && <span className="sr">não lida</span>}
                <time>{c.ultima_entrada_em ? formatarHora(c.ultima_entrada_em) : ""}</time>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function formatarHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
