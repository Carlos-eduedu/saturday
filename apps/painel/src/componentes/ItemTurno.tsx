import type { ReactNode } from "react";
import type { Turno } from "../api";
import { formatarHora } from "../paginas/Inbox";
import { CHAMADAS, dolar, ETAPAS, MOTIVOS_HANDOFF, NOS, rotulo, tokens } from "../rotulos";

// Um turno da IA: caminho no grafo, classificação, chamadas e custo. Usado na
// aba IA da conversa e nas execuções da aba Agente (que passa o cabeçalho).
export function ItemTurno({ t, topo }: { t: Turno; topo?: ReactNode }) {
  return (
    <li className={t.erro ? "turno falhou" : "turno"}>
      <div className="turno-topo">
        <time dateTime={t.criado_em}>{formatarHora(t.criado_em)}</time>
        {topo}
        {t.etapa && <span className="etapa">{rotulo(ETAPAS, t.etapa)}</span>}
        {t.duracao_ms !== null && <span className="turno-duracao">{duracao(t.duracao_ms)}</span>}
        {t.custo_usd !== null && <span className="turno-custo">{dolar(t.custo_usd)}</span>}
      </div>
      <p className="turno-caminho">{t.caminho.map((n) => rotulo(NOS, n)).join(" → ")}</p>
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
    </li>
  );
}

export const duracao = (ms: number) =>
  ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;
