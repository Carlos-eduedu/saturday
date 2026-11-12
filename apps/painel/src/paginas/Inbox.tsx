import {
  type CSSProperties,
  type MouseEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useNavigate } from "react-router";
import { api, type Eu, type Resumo } from "../api";
import { AiChat02Icon, UserCheck01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import SwipeRow, { type SwipeAction } from "../componentes/SwipeRow";
import { Vazio } from "../componentes/Vazio";
import { useAvisos } from "../tempoReal";

// Cores do SwipeRow pelas variáveis do painel: seguem o tema claro e o escuro.
const CORES_SWIPE = {
  "--sr-row": "var(--superficie)",
  "--sr-text": "var(--texto)",
  "--sr-drawer": "var(--superficie-2)",
  "--sr-on-drawer": "var(--texto)",
  "--sr-on-action": "var(--destaque-texto)",
} as CSSProperties;

type Acao = "assumir" | "devolver";

// Com 60% da linha (padrão), no desktop seria preciso arrastar mais de 1200 px.
// shortcut: lido uma vez ao carregar; girar ou redimensionar a janela não muda.
const commitAt = typeof window !== "undefined" && window.innerWidth >= 600 ? 0.35 : 0.6;

// A ação que arrastar faz numa linha; nenhuma quando quem vê não pode agir.
function acaoDa(c: Resumo, eu: Eu): Acao | null {
  if (c.atendimento !== "assumida") return "assumir";
  if (c.atendente_id === eu.id) return "devolver";
  return eu.perfil === "gestor" ? "assumir" : null;
}

const ACOES: Record<Acao, SwipeAction> = {
  assumir: {
    id: "assumir",
    label: "Assumir",
    icon: <HugeiconsIcon icon={UserCheck01Icon} size={20} strokeWidth={2} />,
  },
  devolver: {
    id: "devolver",
    label: "Devolver",
    icon: <HugeiconsIcon icon={AiChat02Icon} size={20} strokeWidth={2} />,
  },
};

const FILAS = [
  { valor: "", rotulo: "Todas" },
  { valor: "ia", rotulo: "Com a IA" },
  { valor: "handoff", rotulo: "Aguardando humano" },
  { valor: "assumida", rotulo: "Com humano" },
  { valor: "minhas", rotulo: "Minhas" },
];

const VAZIOS: Record<string, { titulo: string; texto: string }> = {
  "": {
    titulo: "Nenhuma conversa ainda.",
    texto: "As conversas aparecem aqui assim que um cliente escrever.",
  },
  ia: {
    titulo: "Nenhuma conversa com a IA.",
    texto: "Conversas que a IA está atendendo sozinha aparecem aqui.",
  },
  handoff: {
    titulo: "Ninguém aguardando.",
    texto: "Quando a IA passar uma conversa para a equipe, ela aparece aqui.",
  },
  assumida: {
    titulo: "Nenhuma conversa com a equipe.",
    texto: "Conversas assumidas por alguém da equipe aparecem aqui.",
  },
  minhas: {
    titulo: "Nenhuma conversa sua.",
    texto: "Arraste uma conversa para a esquerda para assumir; ela passa a aparecer aqui.",
  },
};

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

  // Soltar depois de arrastar não abre a conversa; o clique simples abre.
  const inicio = useRef<{ x: number; y: number } | null>(null);
  const guardarInicio = (e: PointerEvent) => {
    inicio.current = { x: e.clientX, y: e.clientY };
  };
  const arrastou = (e: MouseEvent) => {
    const p = inicio.current;
    return p !== null && Math.hypot(e.clientX - p.x, e.clientY - p.y) > 8;
  };
  const ignorarSeArrastou = (e: MouseEvent) => {
    if (arrastou(e)) e.preventDefault();
  };
  // O SwipeRow captura o ponteiro: o clique cai na superfície, não no link.
  const navegar = useNavigate();
  const abrirPelaSuperficie = (e: MouseEvent, id: string) => {
    if ((e.target as Element).closest("a, button") || arrastou(e)) return;
    navegar(`/conversas/${id}`);
  };

  async function agir(id: string, acao: Acao) {
    try {
      await (acao === "assumir" ? api.assumir(id) : api.devolver(id));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "falha ao agir na conversa");
    }
    carregar();
  }

  const rotuloFila = FILAS.find((f) => f.valor === fila)?.rotulo ?? "Todas";
  const vazio = busca
    ? {
        titulo: "Nenhum telefone encontrado.",
        texto: "Confira os últimos dígitos ou troque de fila.",
      }
    : (VAZIOS[fila] ?? VAZIOS[""]);

  return (
    <section>
      <h1 className="titulo-tela">
        Conversas{" "}
        <span className="contagem">
          · {rotuloFila} · {conversas.length}
        </span>
      </h1>
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
        <Vazio titulo={vazio.titulo} texto={vazio.texto} />
      ) : (
        <ul className="inbox">
          {conversas.map((c) => (
            <li
              key={c.id}
              className={c.nao_lida ? "nao-lida" : ""}
              onPointerDown={guardarInicio}
              onClick={(e) => abrirPelaSuperficie(e, c.id)}
            >
              {(() => {
                const linha = (
                  <Link
                    to={`/conversas/${c.id}`}
                    // O arrastar nativo do link cancelaria o gesto do SwipeRow.
                    draggable={false}
                    onClick={ignorarSeArrastou}
                  >
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
                );
                const acao = acaoDa(c, eu);
                if (!acao) return linha;
                return (
                  <SwipeRow
                    actions={[ACOES[acao]]}
                    onCommit={() => agir(c.id, acao)}
                    actionColor={acao === "assumir" ? "var(--destaque)" : "var(--ia)"}
                    commitAt={commitAt}
                    height={64}
                    radius={14}
                    label={`Conversa ${c.telefone ?? c.canal}`}
                    style={CORES_SWIPE}
                  >
                    {linha}
                  </SwipeRow>
                );
              })()}
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
