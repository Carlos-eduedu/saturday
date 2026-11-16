import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { api, mensagemDeFalha, type Grafo, type NoDoGrafo, type PassoDoNo, type Turno } from "../api";
import { ETAPAS, MOTIVOS_HANDOFF, NOS, rotulo } from "../rotulos";
import { Dialogo } from "./Dialogo";
import { Falha } from "./Falha";

const INICIO = "__start__";
const FIM = "__end__";


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
  passos,
  verExecucoes,
}: {
  grafo: Grafo;
  destaque: string[];
  passos: EstadoDosPassos;
  verExecucoes?: (no: string) => void;
}) {
  const { pos, largura, altura } = useMemo(() => posicionar(grafo), [grafo]);
  const [escolhido, setEscolhido] = useState<string | null>(null);
  // Muda a chave do desenho para refazer a progressão do começo.
  const [repeticao, setRepeticao] = useState(0);

  // A execução passa da entrada ao primeiro nó e do último ao fim. A posição
  // de cada nó no caminho marca quando ele acende na progressão.
  const caminho = [INICIO, ...destaque, FIM];
  const ordemNaRota = new Map(caminho.map((id, i) => [id, i] as const));
  const passo = passoDaRota(caminho.length);
  const trechoDaRota = (de: string, para: string) => {
    const i = ordemNaRota.get(de);
    return i !== undefined && caminho[i + 1] === para ? i : -1;
  };
  const no = grafo.nos.find((n) => n.id === escolhido) ?? null;
  const tempo = (ms: number) => ({ "--atraso": `${ms}ms`, "--passo": `${passo}ms` }) as CSSProperties;

  // O grafo é mais largo que o celular: durante a progressão, o quadro segue
  // o nó que acende.
  const quadro = useRef<HTMLDivElement>(null);
  const chaveRota = caminho.join(">");
  useEffect(() => {
    const q = quadro.current;
    if (!q) return;
    const nos = chaveRota.split(">");
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
      <p className="grafo-destaque">
        {destaque.map((n) => rotulo(NOS, n)).join(" → ")}
        <span className="grafo-destaque__acoes">
          <button type="button" onClick={() => setRepeticao((r) => r + 1)}>
            Repetir
          </button>
        </span>
      </p>
      <div className="grafo-quadro" ref={quadro}>
        <svg
          key={`${chaveRota}#${repeticao}`}
          className="percorrendo"
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
                style={ordem !== undefined ? tempo(ordem * passo) : undefined}
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
      {no && (
        <DetalheNo
          no={no}
          noCaminho={destaque.includes(no.id)}
          passos={passos}
          verExecucoes={verExecucoes}
          fechar={() => setEscolhido(null)}
        />
      )}
    </div>
  );
}

function DetalheNo({
  no,
  noCaminho,
  passos,
  verExecucoes,
  fechar,
}: {
  no: NoDoGrafo;
  noCaminho: boolean;
  passos: EstadoDosPassos;
  verExecucoes?: (no: string) => void;
  fechar: () => void;
}) {
  const extremo = no.id === INICIO || no.id === FIM;
  return (
    <Dialogo
      titulo={rotulo(NOS, no.id)}
      aoFechar={fechar}
      rodape={
        !extremo &&
        verExecucoes && (
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
        {noCaminho && <EstadoNaExecucao passo={passos} no={no.id} />}
      </div>
    </Dialogo>
  );
}


// ------------------------------------------------------------------ estado

// `undefined` carregando, `null` sem checkpoints (podados), string = erro.
type EstadoDosPassos = PassoDoNo[] | null | undefined | string;

const CAMPOS: Record<string, string> = {
  status: "Situação",
  intent: "Intenção",
  intent_confidence: "Confiança",
  publico: "Público",
  needs_human: "Precisa de humano",
  handoff_reason: "Motivo do handoff",
  aguardando: "Aguardando",
  tentativas_coleta: "Tentativas de coleta",
  tentativas_extrato: "Tentativas do extrato",
  tentativas_resposta: "Respostas sem FAQ",
  oferta_pendente: "Oferta pendente",
  evento_sistema: "Evento do sistema",
  chave_mensagem: "Mensagem fixa",
  modelo_aviso: "Modelo do aviso",
  modelo_envio: "Modelo enviado",
  clt_faq: "Desvio para a FAQ",
  marketing: "Marketing",
  "clt.etapa": "Etapa CLT",
  "clt.passo": "Passo CLT",
  "clt.motivo": "Motivo CLT",
  "clt.erros": "Erros seguidos",
  "clt.novas_simulacoes": "Novas simulações",
  "clt.falhas_pagamento": "Falhas de pagamento",
};

function valorDoCampo(campo: string, valor: PassoDoNo["campos"][number]["valor"]) {
  if (valor === null) return "—";
  if (typeof valor === "boolean") return valor ? "sim" : "não";
  if (campo === "intent_confidence" && typeof valor === "number") return `${Math.round(valor * 100)}%`;
  if (campo === "clt.etapa") return rotulo(ETAPAS, String(valor));
  if (campo === "handoff_reason") return rotulo(MOTIVOS_HANDOFF, String(valor));
  return String(valor);
}

// O estado técnico logo depois do nó, nesta execução; o que o nó mudou vem marcado.
function EstadoNaExecucao({ passo: passos, no }: { passo: EstadoDosPassos; no: string }) {
  let corpo;
  if (passos === undefined) corpo = <p className="nota">Carregando o estado…</p>;
  else if (typeof passos === "string") corpo = <p className="erro">{passos}</p>;
  else if (passos === null)
    corpo = (
      <p className="nota">
        Estado indisponível: os checkpoints desta conversa já foram apagados pela retenção.
      </p>
    );
  else {
    const passo = passos.find((p) => p.no === no);
    corpo = !passo ? (
      <p className="nota">Este nó não gravou estado nesta execução.</p>
    ) : (
      <>
        <dl className="estado-no">
          {passo.campos.map((c) => (
            <div key={c.campo} className={c.mudou ? "mudou" : undefined}>
              <dt>
                {CAMPOS[c.campo] ?? c.campo}
                {c.mudou && <span className="estado-no__mudou">mudou aqui</span>}
              </dt>
              <dd>{valorDoCampo(c.campo, c.valor)}</dd>
            </div>
          ))}
        </dl>
        {passo.ocultos.length > 0 && (
          <p className="nota">
            Também mudou (texto ou dado pessoal, não exibido): {passo.ocultos.join(", ")}.
          </p>
        )}
      </>
    );
  }
  return (
    <section className="estado-execucao" aria-label="Estado nesta execução">
      <h3>Estado depois deste nó</h3>
      {corpo}
    </section>
  );
}

// O caminho de uma execução desenhado no grafo do agente. Abre por "Ver grafo"
// nas execuções da aba Agente e na aba IA da conversa; o detalhe de cada nó do
// caminho mostra o estado técnico daquela execução. `verExecucoes` (só na aba
// Agente) filtra a lista pelo nó escolhido.
export function ModalGrafo({
  turno,
  aoFechar,
  verExecucoes,
}: {
  turno: Turno;
  aoFechar: () => void;
  verExecucoes?: (no: string) => void;
}) {
  const [grafo, setGrafo] = useState<Grafo | null>(null);
  const [passos, setPassos] = useState<EstadoDosPassos>(undefined);
  useEffect(() => {
    api
      .passos(turno.id)
      .then((r) => setPassos(r.passos))
      .catch((e: unknown) => setPassos(mensagemDeFalha(e, "carregar o estado")));
  }, [turno.id]);
  const [erro, setErro] = useState("");
  const [tentativa, setTentativa] = useState(0);
  useEffect(() => {
    setErro("");
    api
      .grafo()
      .then(setGrafo)
      .catch((e: unknown) => setErro(mensagemDeFalha(e, "carregar o grafo")));
  }, [tentativa]);

  return (
    <Dialogo titulo="Caminho no grafo" aoFechar={aoFechar} largo classe="dialogo--grafo">
      {erro ? (
        <Falha titulo="Não deu para carregar o grafo." texto={erro} aoTentar={() => setTentativa((t) => t + 1)} />
      ) : !grafo ? (
        <p className="centro">Carregando…</p>
      ) : (
        <VisaoGrafo grafo={grafo} destaque={turno.caminho} passos={passos} verExecucoes={verExecucoes} />
      )}
    </Dialogo>
  );
}
