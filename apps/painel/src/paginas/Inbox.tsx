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
import { api, type Eu, type Resumo, type Usuario } from "../api";
import { AiChat02Icon, UserCheck01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import SwipeRow, { type SwipeAction } from "../componentes/SwipeRow";
import { Vazio } from "../componentes/Vazio";
import { ATENCAO, AUTORES, ETAPAS, MOTIVOS_HANDOFF, relativo, rotulo } from "../rotulos";
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

// Tempo para desfazer: a ação só vai para a API depois disso.
const DESFAZER_MS = 5000;

interface Pendente {
  id: string;
  acao: Acao;
  rotulo: string;
  timer: number;
}

function chamarApi(p: Pendente) {
  return p.acao === "assumir" ? api.assumir(p.id) : api.devolver(p.id);
}

// Com 60% da linha (padrão), no desktop seria preciso arrastar mais de 1200 px.
// shortcut: lido uma vez ao carregar; girar ou redimensionar a janela não muda.
const largo = typeof window !== "undefined" && window.innerWidth >= 600;
const commitAt = largo ? 0.35 : 0.6;
// Duas linhas de conteúdo; no celular a meta desce para uma terceira.
const altura = largo ? 76 : 112;

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

function textoDaEspera(c: Resumo, agora: number): string {
  if (!c.aguardando_desde) return relativo(c.ultima_atividade, agora);
  const quanto = relativo(c.aguardando_desde, agora);
  return quanto === "agora" ? "cliente acabou de escrever" : `cliente espera ${quanto}`;
}

export const ROTULO_ATENDIMENTO = { ia: "IA", handoff: "Handoff", assumida: "Assumida" } as const;

export function Inbox({ eu }: { eu: Eu }) {
  const [fila, setFila] = useState("");
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

  // A espera relativa ("há 3 min") anda sozinha, sem recarregar a lista.
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setAgora(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const pedemAtencao = conversas.filter((c) => c.atencao.length > 0).length;

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

  // Quem é o dono atual, para a confirmação de tomar a conversa de outra pessoa.
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  useEffect(() => {
    api
      .usuarios()
      .then(setUsuarios)
      .catch(() => undefined);
  }, []);
  const nomeDe = (id: string | null) => usuarios.find((u) => u.id === id)?.email ?? "outra pessoa";

  // Assumir e devolver esperam 5 s antes de ir para a API: dá para desfazer
  // sem endpoint novo e sem adivinhar o estado anterior (IA, handoff ou dono).
  const [pendente, setPendente] = useState<Pendente | null>(null);
  const pendenteRef = useRef<Pendente | null>(null);
  // O SwipeRow que dobrou só volta remontado: a versão entra na chave.
  const [versao, setVersao] = useState(0);

  const executar = useCallback(
    async (p: Pendente) => {
      try {
        await chamarApi(p);
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não deu para concluir a ação. Tente de novo.");
        setVersao((v) => v + 1);
      }
      carregar();
    },
    [carregar],
  );

  // Saiu da tela com uma ação esperando: ela vale na hora, não se perde.
  useEffect(
    () => () => {
      const p = pendenteRef.current;
      if (p) {
        window.clearTimeout(p.timer);
        void chamarApi(p).catch(() => undefined);
      }
    },
    [],
  );

  function agir(c: Resumo, acao: Acao) {
    if (pendenteRef.current?.id === c.id) return;
    const deOutro = acao === "assumir" && c.atendimento === "assumida" && c.atendente_id !== eu.id;
    if (
      deOutro &&
      !window.confirm(
        `Assumir a conversa que está com ${nomeDe(c.atendente_id)}? Essa pessoa deixa de ser a dona dela.`,
      )
    ) {
      setVersao((v) => v + 1);
      return;
    }
    // Uma ação esperando por vez: a anterior vale na hora.
    const anterior = pendenteRef.current;
    if (anterior) {
      window.clearTimeout(anterior.timer);
      void executar(anterior);
    }
    const p: Pendente = { id: c.id, acao, rotulo: c.telefone ?? c.canal, timer: 0 };
    p.timer = window.setTimeout(() => {
      pendenteRef.current = null;
      setPendente(null);
      void executar(p);
    }, DESFAZER_MS);
    pendenteRef.current = p;
    setPendente(p);
  }

  function desfazer() {
    const p = pendenteRef.current;
    if (!p) return;
    window.clearTimeout(p.timer);
    pendenteRef.current = null;
    setPendente(null);
    setVersao((v) => v + 1);
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
          {pedemAtencao > 0 && ` · ${pedemAtencao} pedem atenção`}
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
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {conversas.length === 0 ? (
        <Vazio titulo={vazio.titulo} texto={vazio.texto} />
      ) : (
        <ul className="inbox">
          {conversas.map((c) => (
            <li
              key={`${c.id}-${versao}`}
              className={[c.nao_lida && "nao-lida", c.atencao.length > 0 && "pede-atencao"]
                .filter(Boolean)
                .join(" ")}
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
                    <span className="linha-conteudo">
                      <span className="previa">
                        {c.ultima_mensagem ? (
                          <>
                            <span className={`autor-previa autor-${c.ultima_mensagem.autor}`}>
                              {rotulo(AUTORES, c.ultima_mensagem.autor)}:
                            </span>{" "}
                            {c.ultima_mensagem.texto || "—"}
                          </>
                        ) : (
                          <span className="sem-previa">Sem mensagens ainda</span>
                        )}
                      </span>
                      <span className="linha-detalhe">
                        <span className="telefone">{c.telefone ?? c.canal}</span>
                        {c.canal === "evolution" && <span>Evolution</span>}
                        {c.canal === "whatsapp" && (
                          <span className={c.janela_aberta ? "janela aberta" : "janela fechada"}>
                            {c.janela_aberta ? "janela aberta" : "janela fechada"}
                          </span>
                        )}
                        {c.motivo_handoff && (
                          <span className="motivo">
                            {rotulo(MOTIVOS_HANDOFF, c.motivo_handoff)}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="linha-meta">
                      {c.atencao.length > 0 && (
                        <span className="atencao">
                          {c.atencao.map((a) => rotulo(ATENCAO, a)).join(" · ")}
                        </span>
                      )}
                      <span className="linha-estado">
                        {c.etapa && <span className="etapa">{rotulo(ETAPAS, c.etapa)}</span>}
                        <span className={`selo selo-${c.atendimento}`}>
                          {ROTULO_ATENDIMENTO[c.atendimento]}
                          {c.atendente_id === eu.id ? " (você)" : ""}
                        </span>
                        <time
                          dateTime={c.aguardando_desde ?? c.ultima_atividade}
                          title={formatarHora(c.aguardando_desde ?? c.ultima_atividade)}
                          className={c.aguardando_desde ? "espera" : ""}
                        >
                          {textoDaEspera(c, agora)}
                        </time>
                      </span>
                    </span>
                    {c.nao_lida && <span className="sr">não lida</span>}
                  </Link>
                );
                const acao = acaoDa(c, eu);
                if (!acao) return linha;
                const esperando = pendente?.id === c.id;
                return (
                  <SwipeRow
                    actions={[ACOES[acao]]}
                    onCommit={() => agir(c, acao)}
                    actionColor={acao === "assumir" ? "var(--destaque)" : "var(--ia)"}
                    commitAt={commitAt}
                    height={altura}
                    radius={14}
                    label={`Conversa ${c.telefone ?? c.canal}`}
                    style={CORES_SWIPE}
                  >
                    <span className="linha-com-acao">
                      {linha}
                      <button
                        type="button"
                        className={acao === "assumir" ? "acao-linha principal" : "acao-linha"}
                        disabled={esperando}
                        onClick={() => agir(c, acao)}
                      >
                        {esperando ? "Aguarde…" : ACOES[acao].label}
                      </button>
                    </span>
                  </SwipeRow>
                );
              })()}
            </li>
          ))}
        </ul>
      )}
      {pendente && (
        <div className="aviso-flutuante" role="status">
          <span>
            {pendente.acao === "assumir" ? "Assumindo" : "Devolvendo para a IA"} {pendente.rotulo}
          </span>
          <button type="button" onClick={desfazer}>
            Desfazer
          </button>
        </div>
      )}
    </section>
  );
}

export function formatarHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
