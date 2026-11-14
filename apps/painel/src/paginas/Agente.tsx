import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import {
  api,
  ErroApi,
  type Execucao,
  type Grafo,
  type NoDoGrafo,
  type SituacaoExecucao,
} from "../api";
import { Abas } from "../componentes/Abas";
import { Dialogo } from "../componentes/Dialogo";
import { Falha } from "../componentes/Falha";
import GlideSelect from "../componentes/GlideSelect";
import { ItemTurno } from "../componentes/ItemTurno";
import { Vazio } from "../componentes/Vazio";
import { NOS, rotulo } from "../rotulos";
import { useAvisos } from "../tempoReal";
import { AbaConhecimento } from "./AgenteConhecimento";
import { AbaModelos, AbaVersoes } from "./AgenteModelos";

type Aba = "grafo" | "execucoes" | "modelos" | "conhecimento" | "versoes";
const INICIO = "__start__";
const FIM = "__end__";

const mensagem = (e: unknown) => (e instanceof ErroApi ? e.message : "falha ao carregar");

// Aba Agente: o grafo que roda (lido da estrutura compilada na API) e as
// execuções de todas as conversas, ao vivo; os modelos de cada etapa e as
// versões da configuração (editar exige a permissão "editar o agente").
export function Agente() {
  const [aba, setAba] = useState<Aba>("grafo");
  const [grafo, setGrafo] = useState<Grafo | null>(null);
  const [erro, setErro] = useState("");
  // Caminho de uma execução escolhida em "Ver no grafo".
  const [destaque, setDestaque] = useState<string[] | null>(null);
  const [filtroNo, setFiltroNo] = useState("");

  const carregar = useCallback(() => {
    setErro("");
    api.grafo().then(setGrafo).catch((e: unknown) => setErro(mensagem(e)));
  }, []);
  useEffect(carregar, [carregar]);

  return (
    <div className="agente">
      <h1 className="titulo-tela">Agente</h1>
      <Abas
        rotulo="Agente"
        opcoes={[
          ["grafo", "Grafo"],
          ["execucoes", "Execuções"],
          ["modelos", "Modelos"],
          ["conhecimento", "Conhecimento"],
          ["versoes", "Versões"],
        ]}
        valor={aba}
        mudar={setAba}
      />
      {aba === "grafo" &&
        (erro ? (
          <Falha titulo="Não deu para carregar o grafo." texto={erro} aoTentar={carregar} />
        ) : !grafo ? (
          <p className="centro">Carregando…</p>
        ) : (
          <VisaoGrafo
            grafo={grafo}
            destaque={destaque}
            limparDestaque={() => setDestaque(null)}
            verExecucoes={(no) => {
              setFiltroNo(no);
              setAba("execucoes");
            }}
          />
        ))}
      {aba === "modelos" && <AbaModelos />}
      {aba === "conhecimento" && <AbaConhecimento />}
      {aba === "versoes" && <AbaVersoes />}
      {aba === "execucoes" && (
        <ListaExecucoes
          nos={grafo?.nos.filter((n) => n.id !== INICIO && n.id !== FIM) ?? []}
          filtroNo={filtroNo}
          mudarFiltroNo={setFiltroNo}
          verNoGrafo={(caminho) => {
            setDestaque(caminho);
            setAba("grafo");
          }}
        />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ grafo

const LARGURA_NO = 176;
const ALTURA_NO = 48;
const VAO_X = 20;
const VAO_Y = 64;
const MARGEM = 12;

interface Posicao {
  x: number;
  y: number;
}

// Camadas pelo caminho mais longo desde a entrada (o grafo é acíclico); o fim
// fica sempre na última. Dentro da camada, ordena pela média dos predecessores
// para cruzar menos arestas.
function posicionar(grafo: Grafo): { pos: Map<string, Posicao>; largura: number; altura: number } {
  const camada = new Map<string, number>([[INICIO, 0]]);
  for (let mudou = true, voltas = 0; mudou && voltas < grafo.nos.length; voltas++) {
    mudou = false;
    for (const a of grafo.arestas) {
      const origem = camada.get(a.de);
      if (origem === undefined || a.para === FIM) continue;
      if ((camada.get(a.para) ?? -1) < origem + 1) {
        camada.set(a.para, origem + 1);
        mudou = true;
      }
    }
  }
  const ultima = Math.max(0, ...camada.values()) + 1;
  camada.set(FIM, ultima);
  grafo.nos.forEach((n) => camada.has(n.id) || camada.set(n.id, ultima - 1));

  const camadas: string[][] = Array.from({ length: ultima + 1 }, () => []);
  grafo.nos.forEach((n) => camadas[camada.get(n.id) ?? 0].push(n.id));

  const ordem = new Map<string, number>();
  camadas.forEach((ids) => {
    const media = (id: string) => {
      const antes = grafo.arestas.filter((a) => a.para === id && ordem.has(a.de));
      return antes.length ? antes.reduce((s, a) => s + (ordem.get(a.de) ?? 0), 0) / antes.length : 0;
    };
    ids.sort((a, b) => media(a) - media(b));
    ids.forEach((id, i) => ordem.set(id, i - (ids.length - 1) / 2));
  });

  const maior = Math.max(...camadas.map((c) => c.length));
  const largura = maior * LARGURA_NO + (maior - 1) * VAO_X + 2 * MARGEM;
  const pos = new Map<string, Posicao>();
  camadas.forEach((ids, nivel) =>
    ids.forEach((id) =>
      pos.set(id, {
        x: largura / 2 + (ordem.get(id) ?? 0) * (LARGURA_NO + VAO_X) - LARGURA_NO / 2,
        y: MARGEM + nivel * (ALTURA_NO + VAO_Y),
      }),
    ),
  );
  return { pos, largura, altura: camadas.length * (ALTURA_NO + VAO_Y) - VAO_Y + 2 * MARGEM };
}

// Duração de cada passo da progressão: o caminho inteiro cabe em ~3 s.
const passoDaRota = (n: number) => Math.min(280, Math.round(3000 / Math.max(1, n)));

function VisaoGrafo({
  grafo,
  destaque,
  limparDestaque,
  verExecucoes,
}: {
  grafo: Grafo;
  destaque: string[] | null;
  limparDestaque: () => void;
  verExecucoes: (no: string) => void;
}) {
  const { pos, largura, altura } = useMemo(() => posicionar(grafo), [grafo]);
  const [escolhido, setEscolhido] = useState<string | null>(null);
  // Muda a chave do desenho para refazer a progressão do começo.
  const [repeticao, setRepeticao] = useState(0);

  // A execução passa da entrada ao primeiro nó e do último ao fim. A posição
  // de cada nó no caminho marca quando ele acende na progressão.
  const caminho = destaque ? [INICIO, ...destaque, FIM] : [];
  const ordemNaRota = new Map(caminho.map((id, i) => [id, i] as const));
  const passo = passoDaRota(caminho.length);
  const trechoDaRota = (de: string, para: string) => {
    const i = ordemNaRota.get(de);
    return i !== undefined && caminho[i + 1] === para ? i : -1;
  };
  // Sem caminho, o grafo entra camada a camada, da entrada ao fim.
  const camadaDe = (y: number) => Math.round((y - MARGEM) / (ALTURA_NO + VAO_Y));
  const no = grafo.nos.find((n) => n.id === escolhido) ?? null;
  const tempo = (ms: number) => ({ "--atraso": `${ms}ms`, "--passo": `${passo}ms` }) as CSSProperties;

  // O grafo é mais largo que o celular: durante a progressão, o quadro segue
  // o nó que acende; sem caminho, abre centrado na entrada.
  const quadro = useRef<HTMLDivElement>(null);
  const chaveRota = caminho.join(">");
  useEffect(() => {
    const q = quadro.current;
    if (!q) return;
    const nos = chaveRota ? chaveRota.split(">") : [];
    if (!nos.length) {
      q.scrollLeft = (q.scrollWidth - q.clientWidth) / 2;
      return;
    }
    const suave = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    const timers = nos.map((id, i) =>
      window.setTimeout(() => {
        q.querySelector(`[data-no="${CSS.escape(id)}"]`)?.scrollIntoView({
          behavior: suave,
          block: "nearest",
          inline: "center",
        });
      }, i * passoDaRota(nos.length)),
    );
    return () => timers.forEach(clearTimeout);
  }, [chaveRota, repeticao]);

  return (
    <div className="grafo-tela">
      {destaque && (
        <p className="grafo-destaque">
          Mostrando o caminho de uma execução: {destaque.map((n) => rotulo(NOS, n)).join(" → ")}
          <span className="grafo-destaque__acoes">
            <button type="button" onClick={() => setRepeticao((r) => r + 1)}>
              Repetir
            </button>
            <button type="button" onClick={limparDestaque}>
              Limpar
            </button>
          </span>
        </p>
      )}
      <div className="grafo-quadro" ref={quadro}>
        <svg
          key={`${chaveRota}#${repeticao}`}
          className={destaque ? "percorrendo" : "revelando"}
          viewBox={`0 0 ${largura} ${altura}`}
          width={largura}
          height={altura}
          role="group"
          aria-label="Grafo do agente"
        >
          <defs>
            <marker id="seta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" className="grafo-seta" />
            </marker>
          </defs>
          {grafo.arestas.map((a) => {
            const de = pos.get(a.de);
            const para = pos.get(a.para);
            if (!de || !para) return null;
            const x1 = de.x + LARGURA_NO / 2;
            const y1 = de.y + ALTURA_NO;
            const x2 = para.x + LARGURA_NO / 2;
            const y2 = para.y;
            const meio = (y1 + y2) / 2;
            const d = `M${x1},${y1} C${x1},${meio} ${x2},${meio} ${x2},${y2}`;
            const trecho = trechoDaRota(a.de, a.para);
            if (trecho < 0)
              return (
                <path
                  key={`${a.de}-${a.para}`}
                  d={d}
                  className={`grafo-aresta${a.condicional ? " condicional" : ""}`}
                  markerEnd="url(#seta)"
                  style={tempo(camadaDe(de.y) * 70)}
                />
              );
            // Trecho do caminho: a linha se traça de um nó ao outro e a ponta
            // aparece quando chega. A curva sempre entra no nó na vertical.
            return (
              <g key={`${a.de}-${a.para}`} className="grafo-trecho" style={tempo(trecho * passo)}>
                <path d={d} className="grafo-aresta" />
                <path d={d} className="grafo-traco" pathLength={1} />
                <path d={`M${x2 - 5},${y2 - 9} L${x2 + 5},${y2 - 9} L${x2},${y2} z`} className="grafo-ponta" />
              </g>
            );
          })}
          {grafo.nos.map((n) => {
            const p = pos.get(n.id);
            if (!p) return null;
            const extremo = n.id === INICIO || n.id === FIM;
            const ordem = ordemNaRota.get(n.id);
            const classes = [
              "grafo-no",
              extremo && "extremo",
              ordem !== undefined && "rota",
              escolhido === n.id && "escolhido",
            ]
              .filter(Boolean)
              .join(" ");
            const raio = extremo ? ALTURA_NO / 2 : 10;
            return (
              <g
                key={n.id}
                data-no={n.id}
                className={classes}
                transform={`translate(${p.x},${p.y})`}
                style={tempo(ordem !== undefined ? ordem * passo : camadaDe(p.y) * 70)}
                role="button"
                tabIndex={0}
                aria-haspopup="dialog"
                aria-label={`${rotulo(NOS, n.id)}, ${n.passagens_24h} passagens em 24 horas`}
                onClick={() => setEscolhido(n.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setEscolhido(n.id);
                  }
                }}
              >
                {ordem !== undefined && (
                  <rect className="grafo-halo" width={LARGURA_NO} height={ALTURA_NO} rx={raio} />
                )}
                <rect width={LARGURA_NO} height={ALTURA_NO} rx={raio} />
                <text x={12} y={20} className="grafo-nome">
                  {rotulo(NOS, n.id)}
                </text>
                <text x={12} y={37} className="grafo-meta">
                  {n.modelo ? "IA · " : ""}
                  {n.passagens_24h} em 24 h
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="nota">
        Linha tracejada: caminho decidido em código conforme o estado. Toque num nó para ver os
        detalhes.
      </p>
      {no && <DetalheNo no={no} verExecucoes={verExecucoes} fechar={() => setEscolhido(null)} />}
    </div>
  );
}

function DetalheNo({
  no,
  verExecucoes,
  fechar,
}: {
  no: NoDoGrafo;
  verExecucoes: (no: string) => void;
  fechar: () => void;
}) {
  const extremo = no.id === INICIO || no.id === FIM;
  return (
    <Dialogo
      titulo={rotulo(NOS, no.id)}
      aoFechar={fechar}
      rodape={
        !extremo && (
          <button type="button" onClick={() => verExecucoes(no.id)}>
            Ver execuções que passaram aqui
          </button>
        )
      }
    >
      <div className="grafo-detalhe">
        <code>{no.id}</code>
        {no.descricao && <p>{no.descricao}</p>}
        <dl>
          <div>
            <dt>Modelo</dt>
            <dd>
              {no.modelo ? (
                <>
                  {no.modelo.valor || <span className="erro">não configurado</span>}{" "}
                  <span className="nota">({no.modelo.variavel})</span>
                </>
              ) : (
                "Nenhum: decisão em código"
              )}
            </dd>
          </div>
          <div>
            <dt>Passagens nas últimas 24 h</dt>
            <dd>{no.passagens_24h}</dd>
          </div>
        </dl>
      </div>
    </Dialogo>
  );
}

// ------------------------------------------------------------------ execuções

function ListaExecucoes({
  nos,
  filtroNo,
  mudarFiltroNo,
  verNoGrafo,
}: {
  nos: NoDoGrafo[];
  filtroNo: string;
  mudarFiltroNo: (no: string) => void;
  verNoGrafo: (caminho: string[]) => void;
}) {
  const [situacao, setSituacao] = useState<SituacaoExecucao>("todas");
  const [lista, setLista] = useState<Execucao[] | null>(null);
  const [temMais, setTemMais] = useState(false);
  const [erro, setErro] = useState("");
  const [carregandoMais, setCarregandoMais] = useState(false);
  // O filtro vigente, para descartar respostas de um filtro que já mudou.
  const chave = `${situacao}|${filtroNo}`;
  const chaveAtual = useRef(chave);
  chaveAtual.current = chave;

  // `reiniciar` troca a lista; sem ele (aviso ao vivo), só entra o que é mais
  // novo e o que já foi paginado fica.
  const primeiraPagina = useCallback((reiniciar = true) => {
    const pedida = `${situacao}|${filtroNo}`;
    api
      .execucoes({ situacao, no: filtroNo || undefined })
      .then((r) => {
        if (chaveAtual.current !== pedida) return;
        setErro("");
        if (reiniciar) {
          setLista(r.execucoes);
          setTemMais(r.tem_mais);
          return;
        }
        setLista((atual) => {
          const topo = atual?.[0]?.id ?? 0;
          return [...r.execucoes.filter((e) => e.id > topo), ...(atual ?? [])];
        });
      })
      .catch((e: unknown) => setErro(mensagem(e)));
  }, [situacao, filtroNo]);

  useEffect(() => {
    setLista(null);
    primeiraPagina();
  }, [primeiraPagina]);

  useAvisos(
    useCallback(
      (aviso) => {
        if (aviso.tipo === "reconectado") {
          setLista(null);
          primeiraPagina();
        } else if (aviso.tipo === "turno") primeiraPagina(false);
      },
      [primeiraPagina],
    ),
  );

  function maisAntigas() {
    if (!lista?.length) return;
    setCarregandoMais(true);
    api
      .execucoes({ situacao, no: filtroNo || undefined, antes_de: lista[lista.length - 1].id })
      .then((r) => {
        setLista((atual) => [...(atual ?? []), ...r.execucoes]);
        setTemMais(r.tem_mais);
      })
      .catch((e: unknown) => setErro(mensagem(e)))
      .finally(() => setCarregandoMais(false));
  }

  return (
    <div className="execucoes">
      <div className="execucoes-filtros">
        <label>
          Situação
          <GlideSelect
            ariaLabel="Situação"
            value={situacao}
            onChange={(v) => setSituacao(v as SituacaoExecucao)}
            menuWidth={220}
            options={[
              { value: "todas", label: "Todas" },
              { value: "erro", label: "Com erro" },
              { value: "handoff", label: "Passadas para a equipe" },
            ]}
          />
        </label>
        <label>
          Passou pelo nó
          <GlideSelect
            ariaLabel="Passou pelo nó"
            value={filtroNo}
            onChange={mudarFiltroNo}
            menuWidth={240}
            options={[
              { value: "", label: "Qualquer" },
              ...nos.map((n) => ({ value: n.id, label: rotulo(NOS, n.id) })),
            ]}
          />
        </label>
        <span className="ao-vivo" title="A lista recebe as execuções novas sem recarregar">
          Ao vivo
        </span>
      </div>

      {erro && lista && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {!lista ? (
        erro ? (
          <Falha titulo="Não deu para carregar as execuções." texto={erro} aoTentar={() => primeiraPagina()} />
        ) : (
          <p className="centro">Carregando…</p>
        )
      ) : lista.length === 0 ? (
        <Vazio
          titulo="Nenhuma execução com esse filtro."
          texto="Cada turno da IA aparece aqui assim que termina."
        />
      ) : (
        <ol className="trilha-lista">
          {lista.map((e) => (
            <ItemTurno
              key={e.id}
              t={e}
              topo={
                <>
                  <Link to={`/conversas/${e.conversa_id}`}>{e.telefone ?? e.canal}</Link>
                  <button type="button" className="link" onClick={() => verNoGrafo(e.caminho)}>
                    Ver no grafo
                  </button>
                </>
              }
            />
          ))}
        </ol>
      )}
      {temMais && lista && lista.length > 0 && (
        <button type="button" onClick={maisAntigas} disabled={carregandoMais}>
          {carregandoMais ? "Carregando…" : "Carregar mais antigas"}
        </button>
      )}
    </div>
  );
}
