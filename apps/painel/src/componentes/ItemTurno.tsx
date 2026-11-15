import { FlowConnectionIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type MouseEvent, type ReactNode, useRef, useState } from "react";
import type { Turno } from "../api";
import { useMidia } from "../midia";
import { COM_BOTAO, CORES_SWIPE, formatarHora } from "../paginas/Inbox";
import SwipeRow from "./SwipeRow";
import { CHAMADAS, dolar, ETAPAS, MOTIVOS_HANDOFF, NOS, rotulo, tokens } from "../rotulos";

// Um turno da IA: caminho no grafo, classificação, chamadas e custo. Usado na
// aba IA da conversa e nas execuções da aba Agente (que passa o cabeçalho).
// `verGrafo` põe o botão no fim da linha do caminho, fora do cabeçalho, que
// na coluna estreita da conversa não tem espaço. No celular, como assumir no
// inbox, é arrastar o turno para a esquerda (ou tocar em "…").
export function ItemTurno({
  t,
  topo,
  verGrafo,
}: {
  t: Turno;
  topo?: ReactNode;
  verGrafo?: () => void;
}) {
  const comBotao = useMidia(COM_BOTAO);
  // O SwipeRow recolhe ao concluir o gesto: remontar devolve o turno à lista.
  const [versao, setVersao] = useState(0);
  const gesto = verGrafo !== undefined && !comBotao;
  const classe = t.erro ? "turno falhou" : "turno";
  // O SwipeRow captura o ponteiro e o toque cai na superfície: um toque (não um
  // arrasto) sobre o link do cabeçalho segue para ele, como no inbox.
  const inicio = useRef<{ x: number; y: number } | null>(null);
  const tocarLink = (e: MouseEvent) => {
    const p = inicio.current;
    if (!p || Math.hypot(e.clientX - p.x, e.clientY - p.y) > 8) return;
    const link = document.elementFromPoint(e.clientX, e.clientY)?.closest("a");
    if (link && e.target !== link) link.click();
  };

  const conteudo = (
    <>
      <div className="turno-topo">
        <time dateTime={t.criado_em}>{formatarHora(t.criado_em)}</time>
        {topo}
        {t.etapa && <span className="etapa">{rotulo(ETAPAS, t.etapa)}</span>}
        {t.duracao_ms !== null && <span className="turno-duracao">{duracao(t.duracao_ms)}</span>}
        {t.custo_usd !== null && <span className="turno-custo">{dolar(t.custo_usd)}</span>}
      </div>
      <div className="turno-linha-caminho">
        <p className="turno-caminho">{t.caminho.map((n) => rotulo(NOS, n)).join(" → ")}</p>
        {verGrafo && !gesto && (
          <button type="button" className="link" onClick={verGrafo}>
            Ver grafo
          </button>
        )}
      </div>
      {t.erro && <p className="erro">Erro: {t.erro}</p>}
      {t.classificacao && (
        <p className="turno-classificacao">
          Intenção: {t.classificacao.intencao ?? "—"} · público: {t.classificacao.publico ?? "—"}
          {t.classificacao.confianca !== null &&
            ` · confiança ${Math.round(t.classificacao.confianca * 100)}%`}
        </p>
      )}
      {t.motivo && <p className="motivo">Motivo: {rotulo(MOTIVOS_HANDOFF, t.motivo)}</p>}
      {t.chamadas.length > 0 && (
        <ul className="turno-chamadas">
          {t.chamadas.map((c, i) => (
            <li
              key={i}
              className={c.status && c.status !== "ok" && !c.status.startsWith("2") ? "falhou" : ""}
            >
              <span>{rotulo(CHAMADAS, c.nome)}</span>
              <span>{c.status ?? "—"}</span>
              <span>{Math.round(c.latencia_ms)} ms</span>
              {c.custo_usd !== null && <span>{dolar(c.custo_usd)}</span>}
              {c.tokens_entrada !== null && (
                <span>
                  {tokens(c.tokens_entrada)}+{tokens(c.tokens_saida ?? 0)} tok
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
  if (!gesto) return <li className={classe}>{conteudo}</li>;
  return (
    <li
      className={`${classe} turno-gesto`}
      onPointerDown={(e) => {
        inicio.current = { x: e.clientX, y: e.clientY };
      }}
      onClick={tocarLink}
    >
      <SwipeRow
        key={versao}
        actions={[
          {
            id: "grafo",
            label: "Ver grafo",
            icon: <HugeiconsIcon icon={FlowConnectionIcon} size={20} strokeWidth={2} />,
          },
        ]}
        onCommit={() => {
          setVersao((v) => v + 1);
          verGrafo();
        }}
        actionColor="var(--destaque)"
        height={96}
        radius={10}
        label={`Turno das ${formatarHora(t.criado_em)}`}
        toggleLabel={`Ver grafo do turno das ${formatarHora(t.criado_em)}`}
        style={CORES_SWIPE}
      >
        <div className="turno-corpo">{conteudo}</div>
      </SwipeRow>
    </li>
  );
}

export const duracao = (ms: number) =>
  ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;
