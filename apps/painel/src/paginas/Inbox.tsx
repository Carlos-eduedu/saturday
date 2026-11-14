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
import { api, type Eu, mensagemDeFalha, type Resumo, type Usuario } from "../api";
import { AiChat02Icon, UserCheck01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { confirmarTomada, textoDoAviso, useAvisoDesfazer } from "../componentes/Desfazer";
import SwipeRow, { type SwipeAction } from "../componentes/SwipeRow";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { ATENCAO, AUTORES, ETAPAS, MOTIVOS_HANDOFF, relativo, rotulo } from "../rotulos";
import { useMidia } from "../midia";
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

// Uma forma de agir por tela: a partir de 600 px, o botão da linha; abaixo,
// arrastar (o mesmo corte do CSS que esconde o botão).
const COM_BOTAO = "(min-width: 600px)";

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

export function textoDaEspera(c: Resumo, agora: number): string {
  if (!c.aguardando_desde) return relativo(c.ultima_atividade, agora);
  const quanto = relativo(c.aguardando_desde, agora);
  return quanto === "agora" ? "cliente acabou de escrever" : `cliente espera ${quanto}`;
}

export const ROTULO_ATENDIMENTO = { ia: "IA", handoff: "Handoff", assumida: "Assumida" } as const;

/** O único motivo que ganha rótulo na linha: falha de envio é invisível sem
 *  ele. "Sem resposta" e "falando de valores" já aparecem no tempo, na etapa e
 *  no fundo tingido — e a lista põe quem espera no topo. */
const ATENCAO_PROPRIAS = new Set(["envio_falhou"]);

// `compacta`: a lista estreita ao lado da conversa aberta (`aberta`), sem
// assumir pela linha; quem age é o cabeçalho da conversa.
export function Inbox({
  eu,
  compacta = false,
  aberta,
}: {
  eu: Eu;
  compacta?: boolean;
  aberta?: string;
}) {
  const comBotao = useMidia(COM_BOTAO);
  const Titulo = compacta ? "h2" : "h1";
  const [fila, setFila] = useState("");
  const [busca, setBusca] = useState("");
  // null = ainda não carregou: não mostra "nenhuma conversa" antes de saber.
  const [conversas, setConversas] = useState<Resumo[] | null>(null);
  const [erro, setErro] = useState("");

  // Digitar na busca dispara um pedido por tecla e os avisos chegam em rajada:
  // só a resposta do último pedido vale, senão uma lista velha cobre a nova.
  const ultimoPedido = useRef(0);
  const carregar = useCallback(() => {
    const pedido = ++ultimoPedido.current;
    api
      .conversas(fila, busca)
      .then((lista) => {
        if (pedido !== ultimoPedido.current) return;
        setConversas(lista);
        setErro("");
      })
      .catch((e: unknown) => {
        if (pedido !== ultimoPedido.current) return;
        setErro(mensagemDeFalha(e, "carregar as conversas"));
      });
  }, [fila, busca]);

  useEffect(carregar, [carregar]);
  useAvisos(carregar);

  // A espera relativa ("há 3 min") anda sozinha, sem recarregar a lista.
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setAgora(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const pedemAtencao = (conversas ?? []).filter((c) => c.atencao.length > 0).length;

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
  const nomeDe = (id: string | null) => usuarios.find((u) => u.id === id)?.nome ?? "outra pessoa";
  // No selo cabe o primeiro nome; o nome inteiro fica na confirmação de tomada
  // e no cabeçalho da conversa, onde há espaço.
  const primeiroNome = (id: string | null) => nomeDe(id).split(" ")[0];

  // Assumir e devolver valem na hora; o aviso deixa desfazer por 5 s.
  const avisar = useAvisoDesfazer();
  const [agindo, setAgindo] = useState("");
  // O SwipeRow que dobrou só volta remontado: a versão entra na chave.
  const [versao, setVersao] = useState(0);

  async function agir(c: Resumo, acao: Acao) {
    if (agindo) return;
    const deOutro = acao === "assumir" && c.atendimento === "assumida" && c.atendente_id !== eu.id;
    if (deOutro && !confirmarTomada(nomeDe(c.atendente_id))) {
      setVersao((v) => v + 1);
      return;
    }
    setAgindo(c.id);
    try {
      await (acao === "assumir" ? api.assumir(c.id) : api.devolver(c.id));
      avisar({ id: c.id, texto: textoDoAviso(acao, c.telefone ?? c.canal), depois: carregar });
    } catch (e) {
      setErro(mensagemDeFalha(e));
    }
    setAgindo("");
    setVersao((v) => v + 1);
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
    <section className="lista-conversas">
      <Titulo className="titulo-tela">
        Conversas{" "}
        <span className="contagem">
          · {rotuloFila}
          {conversas && ` · ${conversas.length}`}
          {pedemAtencao > 0 && ` · ${pedemAtencao} pedem atenção`}
        </span>
      </Titulo>
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
          <span className="sr">Buscar telefone</span>
          <input
            type="search"
            inputMode="numeric"
            placeholder="Buscar telefone"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </label>
      </div>
      {erro && conversas && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {!conversas ? (
        erro ? (
          <Falha titulo="Não deu para carregar as conversas." texto={erro} aoTentar={carregar} />
        ) : (
          <p className="centro">Carregando…</p>
        )
      ) : conversas.length === 0 ? (
        <Vazio titulo={vazio.titulo} texto={vazio.texto} />
      ) : (
        <ul className="inbox">
          {conversas.map((c) => (
            <li
              key={`${c.id}-${versao}`}
              className={c.nao_lida ? "nao-lida" : undefined}
              onPointerDown={guardarInicio}
              onClick={(e) => abrirPelaSuperficie(e, c.id)}
            >
              {(() => {
                // Handoff e "falando de valores" já estão no selo e na etapa logo
                // abaixo; repetir aqui gastava uma linha dizendo o mesmo. Sobra o
                // que não aparece em outro lugar.
                const atencao = c.atencao.filter((a) => ATENCAO_PROPRIAS.has(a));
                const linha = (
                  <Link
                    to={`/conversas/${c.id}`}
                    // O arrastar nativo do link cancelaria o gesto do SwipeRow.
                    draggable={false}
                    onClick={ignorarSeArrastou}
                    aria-current={c.id === aberta ? "page" : undefined}
                  >
                    <span className="linha-conteudo">
                      <span className="linha-identidade">
                        <span className="telefone">{c.telefone ?? c.canal}</span>
                        {/* O canal e a janela só aparecem quando fogem do normal:
                            WhatsApp com janela aberta não precisa de rótulo. */}
                        {(c.canal === "evolution" || !c.janela_aberta) && (
                          <span className="linha-canal">
                            {c.canal === "evolution" ? (
                              <span>Evolution</span>
                            ) : (
                              <span className="janela fechada">janela fechada</span>
                            )}
                          </span>
                        )}
                      </span>
                      <span className="fala">
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
                        {c.motivo_handoff && (
                          <span className="motivo">
                            {rotulo(MOTIVOS_HANDOFF, c.motivo_handoff)}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="linha-meta">
                      {atencao.length > 0 && (
                        <span className="atencao">
                          {atencao.map((a) => rotulo(ATENCAO, a)).join(" · ")}
                        </span>
                      )}
                      <span className="linha-estado">
                        {/* Handoff já aparece no selo ao lado: repetir a etapa
                            gastava uma linha para dizer o mesmo. */}
                        {c.etapa && rotulo(ETAPAS, c.etapa) !== ROTULO_ATENDIMENTO[c.atendimento] && (
                          <span className="etapa">{rotulo(ETAPAS, c.etapa)}</span>
                        )}
                        <span className={`selo selo-${c.atendimento}`}>
                          {ROTULO_ATENDIMENTO[c.atendimento]}
                          {c.atendente_id &&
                            (c.atendente_id === eu.id ? " (você)" : ` · ${primeiroNome(c.atendente_id)}`)}
                        </span>
                      </span>
                      <time
                        dateTime={c.aguardando_desde ?? c.ultima_atividade}
                        title={formatarHora(c.aguardando_desde ?? c.ultima_atividade)}
                        className={c.aguardando_desde ? "espera" : ""}
                      >
                        {relativo(c.aguardando_desde ?? c.ultima_atividade, agora)}
                      </time>
                    </span>
                    {c.nao_lida && <span className="sr">não lida</span>}
                  </Link>
                );
                const acao = compacta ? null : acaoDa(c, eu);
                if (!acao) return linha;
                const esperando = agindo === c.id;
                return (
                  <SwipeRow
                    actions={comBotao ? [] : [ACOES[acao]]}
                    onCommit={() => agir(c, acao)}
                    actionColor={acao === "assumir" ? "var(--destaque)" : "var(--ia)"}
                    // Duas linhas de conteúdo; no celular, identidade, fala e meta ficam em linhas próprias.
                    height={comBotao ? 76 : 136}
                    radius={14}
                    label={`Conversa ${c.telefone ?? c.canal}`}
                    style={CORES_SWIPE}
                  >
                    <span className="linha-com-acao">
                      {linha}
                      <button
                        type="button"
                        // Cobalto só onde a equipe é chamada: o resto fica secundário.
                        className={
                          acao === "assumir" && c.atencao.length > 0
                            ? "acao-linha principal"
                            : "acao-linha"
                        }
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
    </section>
  );
}

export function formatarHora(iso: string): string {
  const data = new Date(iso);
  const agora = new Date();
  const hora = data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (data.toDateString() === agora.toDateString()) return hora;
  const dia = data.toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    ...(data.getFullYear() === agora.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${dia}, ${hora}`;
}
