import {
  type CSSProperties,
  type KeyboardEvent as EventoDeTecla,
  type MouseEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { Link, useNavigate } from "react-router";
import { api, type Contagens, type Eu, mensagemDeFalha, type Resumo, type Usuario } from "../api";
import {
  AiChat02Icon,
  Cancel01Icon,
  MoreHorizontalIcon,
  UserCheck01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useConfirmar } from "../componentes/Confirmar";
import { pedidoDeTomada, textoDoAviso, useAvisoDesfazer } from "../componentes/Desfazer";
import SwipeRow, { type SwipeAction } from "../componentes/SwipeRow";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { ATENCAO, AUTORES, ETAPAS, MOTIVOS_HANDOFF, relativo, rotulo } from "../rotulos";
import { useMidia } from "../midia";
import type { Aviso } from "../tempoReal";
import { useRecurso } from "../useRecurso";

// Cores do SwipeRow pelas variáveis do painel: seguem o tema claro e o escuro.
export const CORES_SWIPE = {
  "--sr-row": "var(--superficie)",
  "--sr-text": "var(--texto)",
  "--sr-drawer": "var(--superficie-2)",
  "--sr-on-drawer": "var(--texto)",
  "--sr-on-action": "var(--destaque-texto)",
} as CSSProperties;

type Acao = "assumir" | "devolver";

// Uma forma de agir por tela: a partir de 600 px, o botão da linha; abaixo,
// arrastar (o mesmo corte do CSS que esconde o botão).
export const COM_BOTAO = "(min-width: 600px)";
const RECARREGAM = new Set<Aviso["tipo"]>(["mensagem", "conversa", "alerta", "turno", "reconectado"]);

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

const FILAS: { valor: "" | Exclude<keyof Contagens, "todas" | "atencao">; rotulo: string }[] = [
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
    texto:
      "Assuma uma conversa pelo botão da linha (no celular, arraste-a para a esquerda); ela passa a aparecer aqui.",
  },
};

const TITULO = "Saturday · Painel";

// A dica do gesto aparece uma vez por sessão, no celular. Sem armazenamento
// (aba privada), aparece de novo: é só uma linha de texto.
const DICA_GESTO = "saturday.dica-gesto";
function dicaJaVista(): boolean {
  try {
    return sessionStorage.getItem(DICA_GESTO) === "1";
  } catch {
    return false;
  }
}
function marcarDica(): void {
  try {
    sessionStorage.setItem(DICA_GESTO, "1");
  } catch {
    // sem armazenamento, a dica volta na próxima visita
  }
}

// Quando chegou a última fala do cliente, por conversa: comparar duas cargas
// diz quem escreveu de novo, sem anunciar cada aviso do tempo real.
const falasDoCliente = (lista: Resumo[]) =>
  new Map(
    lista.map((c) => [c.id, c.ultima_mensagem?.autor === "cliente" ? c.ultima_mensagem.em : ""]),
  );

// Atalhos da lista. Valem fora de campos de texto.
const ATALHOS =
  "Atalhos: / busca; J e K (ou as setas na lista) andam entre as conversas; Enter abre; na conversa, A assume e D devolve.";

export function textoDaEspera(c: Resumo, agora: number): string {
  if (!c.aguardando_desde) return relativo(c.ultima_atividade, agora);
  const quanto = relativo(c.aguardando_desde, agora);
  if (quanto === "agora") return "cliente acabou de escrever";
  // "ontem" e "12/11" pedem o "desde"; "há 3 min" já se lê sozinho.
  return `cliente espera ${quanto.startsWith("há") ? quanto : `desde ${quanto}`}`;
}

export const ROTULO_ATENDIMENTO = { ia: "IA", handoff: "Handoff", assumida: "Assumida" } as const;

/** O único motivo que ganha rótulo na linha: falha de envio é invisível sem
 *  ele. "Sem resposta" e "falando de valores" já aparecem no tempo, na etapa e
 *  no filtro "pedem atenção" — e a lista põe quem espera no topo. */
const ATENCAO_PROPRIAS = new Set(["envio_falhou"]);

// `compacta`: a lista estreita ao lado da conversa aberta (`aberta`). Nela, só
// a linha em handoff ganha o botão Assumir (o handoff é quem chama a equipe); o
// resto se faz no cabeçalho da conversa aberta.
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
  // Digitar na busca dispara um pedido por tecla e os avisos chegam em rajada:
  // o recurso só aceita a resposta do último pedido. Só o que muda a linha ou
  // as contagens recarrega: aviso do Agente, da Granatech ou da homologação
  // chegava em rajada e refazia dois pedidos à toa.
  const chave = `${fila}|${busca}`;
  const carga = useRecurso(chave, () => Promise.all([api.conversas(fila, busca), api.contagens()]), {
    recarrega: (aviso) => RECARREGAM.has(aviso.tipo),
    manter: true,
  });
  const { carregar } = carga;
  // null = ainda não carregou: não mostra "nenhuma conversa" antes de saber.
  const conversas = carga.dado?.[0] ?? null;
  // Contagens das abas e do título da aba do navegador, em toda a base.
  const contagens = carga.dado?.[1] ?? null;
  // De que fila e busca é a lista à mostra: trocar de fila mantém a anterior,
  // esmaecida, até a nova chegar (em vez de piscar "Carregando…").
  const carregada = carga.chaveDoDado ?? "";
  // Falha de uma ação (assumir, devolver); a de carga vem do recurso.
  const [erroDaAcao, setErro] = useState("");
  const erro =
    erroDaAcao || (carga.falha === null ? "" : mensagemDeFalha(carga.falha, "carregar as conversas"));
  const [soAtencao, setSoAtencao] = useState(false);

  // Leitor de tela: avisa quem escreveu, agrupado em 1,5 s, e não a cada aviso.
  const [anuncio, setAnuncio] = useState("");
  const falasAntes = useRef<Map<string, string> | null>(null);
  // De que fila e busca são as falas guardadas: trocar de lista não é mensagem nova.
  const listaAntes = useRef("");
  const novas = useRef<string[]>([]);
  const relogioAnuncio = useRef(0);
  useEffect(() => () => window.clearTimeout(relogioAnuncio.current), []);
  const anunciar = useCallback((lista: Resumo[], chave: string) => {
    const antes = listaAntes.current === chave ? falasAntes.current : null;
    falasAntes.current = falasDoCliente(lista);
    listaAntes.current = chave;
    if (!antes) return;
    for (const [id, em] of falasAntes.current) {
      if (!em || antes.get(id) === em) continue;
      const c = lista.find((r) => r.id === id);
      if (c) novas.current.push(c.telefone ?? c.canal);
    }
    if (novas.current.length === 0) return;
    window.clearTimeout(relogioAnuncio.current);
    relogioAnuncio.current = window.setTimeout(() => {
      const quem = [...new Set(novas.current)];
      novas.current = [];
      setAnuncio(
        quem.length === 1 ? `Nova mensagem de ${quem[0]}` : `Novas mensagens em ${quem.length} conversas`,
      );
      // Limpa depois, para o mesmo texto poder ser anunciado de novo.
      relogioAnuncio.current = window.setTimeout(() => setAnuncio(""), 5000);
    }, 1500);
  }, []);

  // Cada lista que chega anuncia as mensagens novas em relação à anterior.
  useEffect(() => {
    if (carga.dado && carga.chaveDoDado !== null) anunciar(carga.dado[0], carga.chaveDoDado);
  }, [carga.dado, carga.chaveDoDado, anunciar]);

  // A espera relativa ("há 3 min") anda sozinha, sem recarregar a lista.
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setAgora(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const pedemAtencao = (conversas ?? []).filter((c) => c.atencao.length > 0).length;
  // Sem ninguém pedindo atenção, o filtro se desliga sozinho.
  const filtrandoAtencao = soAtencao && pedemAtencao > 0;
  const visiveis = filtrandoAtencao
    ? (conversas ?? []).filter((c) => c.atencao.length > 0)
    : conversas;

  // A aba do navegador mostra quantas pedem atenção: dá para ver de outra aba.
  const atencaoTotal = contagens?.atencao ?? 0;
  useEffect(() => {
    document.title = atencaoTotal > 0 ? `(${atencaoTotal}) ${TITULO}` : TITULO;
  }, [atencaoTotal]);
  useEffect(
    () => () => {
      document.title = TITULO;
    },
    [],
  );

  // Teclado: "/" vai para a busca; J e K (e as setas com o foco na lista)
  // andam entre as linhas; Enter abre (é o link). Fora de campos de texto, de
  // diálogo aberto e da lista escondida (celular com conversa aberta).
  const secao = useRef<HTMLElement>(null);
  const campoBusca = useRef<HTMLInputElement>(null);
  useEffect(() => {
    function teclas(e: KeyboardEvent) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      const lista = secao.current;
      if (!lista || lista.getClientRects().length === 0) return;
      const alvo = e.target instanceof HTMLElement ? e.target : null;
      if (alvo?.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])")) return;
      if (document.querySelector("dialog[open]")) return;
      if (e.key === "/") {
        e.preventDefault();
        campoBusca.current?.focus();
        return;
      }
      const naLista = !!alvo && !!lista.querySelector(".inbox")?.contains(alvo);
      const passo =
        e.key === "j" || (naLista && e.key === "ArrowDown")
          ? 1
          : e.key === "k" || (naLista && e.key === "ArrowUp")
            ? -1
            : 0;
      const links = [...lista.querySelectorAll<HTMLAnchorElement>(".inbox li a")];
      if (!passo || links.length === 0) return;
      e.preventDefault();
      const ativo = document.activeElement;
      let base = links.findIndex((l) => !!ativo && !!l.closest("li")?.contains(ativo));
      if (base < 0) base = links.findIndex((l) => l.getAttribute("aria-current") === "page");
      const prox = base < 0 ? (passo > 0 ? 0 : links.length - 1) : base + passo;
      links[Math.min(links.length - 1, Math.max(0, prox))].focus();
    }
    window.addEventListener("keydown", teclas);
    return () => window.removeEventListener("keydown", teclas);
  }, []);

  // Abas com foco itinerante: setas, Home e End trocam de fila.
  const idBase = useId();
  const idPainel = `${idBase}-fila`;
  const abas = useRef<(HTMLButtonElement | null)[]>([]);
  function teclaNaAba(e: EventoDeTecla<HTMLButtonElement>, i: number) {
    const n = FILAS.length;
    const prox =
      e.key === "ArrowRight"
        ? (i + 1) % n
        : e.key === "ArrowLeft"
          ? (i - 1 + n) % n
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? n - 1
              : -1;
    if (prox < 0) return;
    e.preventDefault();
    setFila(FILAS[prox].valor);
    abas.current[prox]?.focus();
  }

  const [dicaVista, setDicaVista] = useState(dicaJaVista);
  const fecharDica = () => {
    marcarDica();
    setDicaVista(true);
  };

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
    // Sem o link no caminho do clique, Ctrl/⌘/Shift não abririam outra aba sozinhos.
    if (e.ctrlKey || e.metaKey || e.shiftKey) window.open(`/conversas/${id}`, "_blank", "noopener");
    else navegar(`/conversas/${id}`);
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
  const confirmar = useConfirmar();
  const [agindo, setAgindo] = useState("");
  // O SwipeRow que dobrou só volta remontado: a versão entra na chave.
  const [versao, setVersao] = useState(0);

  async function agir(c: Resumo, acao: Acao) {
    if (agindo) return;
    const deOutro = acao === "assumir" && c.atendimento === "assumida" && c.atendente_id !== eu.id;
    if (deOutro && !(await confirmar(pedidoDeTomada(nomeDe(c.atendente_id))))) {
      // Desistir remonta o SwipeRow que dobrou com o gesto.
      setVersao((v) => v + 1);
      return;
    }
    setAgindo(c.id);
    setErro("");
    try {
      await (acao === "assumir" ? api.assumir(c.id) : api.devolver(c.id));
      avisar({ id: c.id, texto: textoDoAviso(acao, c.telefone ?? c.canal), depois: carregar });
      // Quem já agiu pela linha não precisa da dica do gesto.
      if (!comBotao) fecharDica();
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

  const desatualizada = conversas !== null && carregada !== `${fila}|${busca}`;
  const mostrarDica =
    !comBotao && !dicaVista && (visiveis ?? []).some((c) => acaoDa(c, eu) !== null);

  return (
    <section ref={secao} className={compacta ? "lista-conversas compacta" : "lista-conversas"}>
      <div className="cabeca-lista">
        <Titulo className="titulo-tela">
          Conversas{" "}
          <span className="contagem">
            · {rotuloFila}
            {visiveis && ` · ${visiveis.length}`}
          </span>
        </Titulo>
        {pedemAtencao > 0 && (
          <button
            type="button"
            className="filtro-atencao"
            aria-pressed={filtrandoAtencao}
            title={filtrandoAtencao ? "Mostrar todas as conversas da fila" : "Mostrar só as que pedem atenção"}
            onClick={() => setSoAtencao(!filtrandoAtencao)}
          >
            {pedemAtencao} {pedemAtencao === 1 ? "pede" : "pedem"} atenção
            {filtrandoAtencao && <HugeiconsIcon icon={Cancel01Icon} size={16} strokeWidth={2} aria-hidden />}
          </button>
        )}
      </div>
      <div className="filtros">
        <div role="tablist" aria-label="Filas">
          {FILAS.map((f, i) => {
            const ativa = fila === f.valor;
            return (
              <button
                key={f.valor}
                ref={(el) => {
                  abas.current[i] = el;
                }}
                id={`${idBase}-aba-${i}`}
                type="button"
                role="tab"
                aria-selected={ativa}
                aria-controls={idPainel}
                tabIndex={ativa ? 0 : -1}
                className={ativa ? "ativo" : ""}
                onClick={() => setFila(f.valor)}
                onKeyDown={(e) => teclaNaAba(e, i)}
              >
                {f.rotulo}
                {/* O lugar da contagem existe antes de ela chegar: as abas não pulam. */}{" "}
                <span className="aba-contagem">{contagens?.[f.valor || "todas"]}</span>
              </button>
            );
          })}
        </div>
        <label>
          <span className="sr">Buscar telefone</span>
          <input
            ref={campoBusca}
            type="search"
            inputMode="numeric"
            placeholder="Buscar telefone"
            aria-keyshortcuts="/"
            title="Atalho: /"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </label>
      </div>
      <p className="sr" role="status">
        {anuncio}
      </p>
      {erro && conversas && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {mostrarDica && (
        <p className="dica-gesto">
          <span>
            Para assumir ou devolver, arraste a conversa para a esquerda ou toque em{" "}
            <HugeiconsIcon icon={MoreHorizontalIcon} size={16} strokeWidth={2} aria-label="Ações" />.
          </span>
          <button type="button" onClick={fecharDica}>
            Entendi
          </button>
        </p>
      )}
      <div
        role="tabpanel"
        id={idPainel}
        aria-labelledby={`${idBase}-aba-${FILAS.findIndex((f) => f.valor === fila)}`}
        aria-busy={!conversas || desatualizada}
        className={desatualizada ? "painel-fila recarregando" : "painel-fila"}
      >
        <p className="sr" id={`${idBase}-atalhos`}>
          {ATALHOS}
        </p>
        {/* A mesma lista, curta e à vista onde há teclado. */}
        <p className="atalhos" aria-hidden="true">
          / busca · J K andam · Enter abre · A assume · D devolve
        </p>
        {!visiveis ? (
          erro ? (
            <Falha titulo="Não deu para carregar as conversas." texto={erro} aoTentar={carregar} />
          ) : (
            <>
              <p className="sr" role="status">
                Carregando as conversas…
              </p>
              <ul className="inbox esqueleto" aria-hidden="true">
                {[0, 1, 2, 3].map((i) => (
                  <li key={i}>
                    <span />
                    <span />
                  </li>
                ))}
              </ul>
            </>
          )
        ) : visiveis.length === 0 ? (
          <Vazio titulo={vazio.titulo} texto={vazio.texto} />
        ) : (
          <ul className="inbox" aria-describedby={`${idBase}-atalhos`}>
            {visiveis.map((c) => (
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
                          {c.membro && <span className="selo-membro">Membro · {c.membro.split(" ")[0]}</span>}
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
                      {/* O motivo da atenção em texto para leitor de tela; não há marca visual na linha. */}
                      {c.atencao.some((a) => !ATENCAO_PROPRIAS.has(a)) && (
                        <span className="sr">
                          Pede atenção:{" "}
                          {c.atencao
                            .filter((a) => !ATENCAO_PROPRIAS.has(a))
                            .map((a) => rotulo(ATENCAO, a))
                            .join(", ")}
                        </span>
                      )}
                    </Link>
                  );
                  const acao = !compacta
                    ? acaoDa(c, eu)
                    : c.atendimento === "handoff" && c.id !== aberta
                      ? acaoDa(c, eu)
                      : null;
                  if (!acao) return linha;
                  const esperando = agindo === c.id;
                  return (
                    <SwipeRow
                      actions={comBotao ? [] : [ACOES[acao]]}
                      onCommit={() => agir(c, acao)}
                      actionColor={acao === "assumir" ? "var(--destaque)" : "var(--ia)"}
                      // Duas linhas de conteúdo; no celular e na lista compacta, identidade,
                      // fala e meta ficam em linhas próprias.
                      height={compacta ? 112 : comBotao ? 76 : 96}
                      radius={14}
                      label={`Conversa ${c.telefone ?? c.canal}`}
                      toggleLabel={`Ações de ${c.telefone ?? c.canal}`}
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
                          {esperando ? (acao === "assumir" ? "Assumindo…" : "Devolvendo…") : ACOES[acao].label}
                        </button>
                      </span>
                    </SwipeRow>
                  );
                })()}
              </li>
            ))}
          </ul>
        )}
      </div>
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
