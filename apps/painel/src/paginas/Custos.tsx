import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type Custos as DadosCustos, mensagemDeFalha } from "../api";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { dolar, tokens } from "../rotulos";
import { useRecurso } from "../useRecurso";

const diaCurto = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

// Aba Operação, só para gestor: o uso da cota da Granatech e os relatórios de
// custos operacionais (IA em US$).
export function Operacao() {
  return (
    <div className="custos operacao">
      <h1 className="titulo-tela">Operação</h1>
      <CotaGranatech />
      <Custos />
    </div>
  );
}

// Uso da cota no mês e em cada dia, contra os tetos (diário e mensal).
function CotaGranatech() {
  const { dado: cota, falha, carregar } = useRecurso("cota-por-dia", api.cotaPorDia);
  const erro = falha === null ? "" : mensagemDeFalha(falha, "carregar a cota");

  if (erro)
    return <Falha titulo="Não deu para carregar a cota da Granatech." texto={erro} aoTentar={carregar} />;
  if (!cota) return <p className="centro">Carregando…</p>;

  const noMes = cota.dias.reduce((soma, d) => soma + d.usadas, 0);
  const hoje = cota.dias.find((d) => d.dia === cota.ate)?.usadas ?? 0;
  const porcento = (usadas: number, teto: number) => (teto ? Math.min(100, (usadas / teto) * 100) : 0);
  // O painel avisa a partir de 80% do mês (alerta de cota).
  const nivel = (usadas: number, teto: number) =>
    usadas >= teto ? "nivel-esgotada" : usadas >= teto * 0.8 ? "nivel-atencao" : "";

  return (
    <section className="cota-operacao">
      <h2>
        Cota da Granatech <span className="contagem">· de {diaCurto(cota.de)} a {diaCurto(cota.ate)}</span>
      </h2>
      <div className="resumo-custos cota-medidores">
        {(
          [
            ["No mês", noMes, cota.teto_mensal],
            ["Hoje", hoje, cota.teto_diario],
          ] as const
        ).map(([rotulo, usadas, teto]) => (
          <div key={rotulo} className={`cota-medidor ${nivel(usadas, teto)}`}>
            <span className="cota-medidor__rotulo">{rotulo}</span>
            <span className="cota-medidor__valor">
              {usadas} <span>de {teto} consultas</span>
            </span>
            <span
              className="cota-medidor__barra"
              role="meter"
              aria-label={`Cota ${rotulo.toLowerCase()}`}
              aria-valuemin={0}
              aria-valuemax={teto}
              aria-valuenow={usadas}
            >
              <span style={{ width: `${porcento(usadas, teto)}%` }} />
            </span>
          </div>
        ))}
      </div>
      <section>
      <h3>Por dia</h3>
      {cota.dias.length === 0 ? (
        <Vazio
          titulo="Nenhuma consulta neste mês."
          texto="Cada consulta à Granatech gasta cota; os dias com consulta aparecem aqui."
        />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Dia</th>
              <th className="num">Consultas</th>
              <th className="num">Do teto diário</th>
            </tr>
          </thead>
          <tbody>
            {cota.dias.map((d) => (
              <tr key={d.dia} className={nivel(d.usadas, cota.teto_diario) || undefined}>
                <td>{diaCurto(d.dia)}</td>
                <td className="num">{d.usadas}</td>
                <td className="num">{Math.round(porcento(d.usadas, cota.teto_diario))}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      </section>
    </section>
  );
}

// Relatórios de custos operacionais: gasto com IA (OpenRouter) em US$, por dia do mês.
function Custos() {
  const [custos, setCustos] = useState<DadosCustos | null>(null);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    setErro("");
    api
      .custos()
      .then(setCustos)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, []);
  useEffect(carregar, [carregar]);

  if (erro) return <Falha titulo="Não deu para carregar os custos." texto={erro} aoTentar={carregar} />;
  if (!custos) return <p className="centro">Carregando…</p>;

  const dia = diaCurto;

  return (
    <section className="relatorio-custos">
      <h2>
        Custos operacionais{" "}
        <span className="contagem">
          · IA em US$, de {dia(custos.de)} a {dia(custos.ate)}
        </span>
      </h2>
      {/* Uma faixa só, sem cartões: três números para conferir, não um painel de vitrine. */}
      <dl className="resumo-custos">
        <div>
          <dt>Hoje</dt>
          <dd className="dado">{dolar(custos.hoje?.custo_usd ?? 0)}</dd>
          <dd className="nota">
            {tokens(custos.hoje?.tokens ?? 0)} tokens · {custos.hoje?.turnos ?? 0} turnos
          </dd>
        </div>
        <div>
          <dt>No período</dt>
          <dd className="dado">{dolar(custos.total.custo_usd)}</dd>
          <dd className="nota">
            {tokens(custos.total.tokens)} tokens · {custos.total.turnos} turnos
          </dd>
        </div>
        <div>
          <dt>Média por turno</dt>
          <dd className="dado">
            {custos.total.turnos ? dolar(custos.total.custo_usd / custos.total.turnos) : "—"}
          </dd>
        </div>
      </dl>

      <section>
        <h3>Por dia</h3>
        {custos.dias.length === 0 ? (
          <Vazio
            titulo="Nenhum turno da IA neste período."
            texto="O custo de cada dia aparece aqui quando a IA atende alguém, com o valor que o OpenRouter cobrou por turno."
          />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Dia</th>
                <th className="num">Custo</th>
                <th className="num">Tokens</th>
                <th className="num">Turnos</th>
              </tr>
            </thead>
            <tbody>
              {custos.dias.map((d) => (
                <tr key={d.dia}>
                  <td>{dia(d.dia)}</td>
                  <td className="num">{dolar(d.custo_usd)}</td>
                  <td className="num">{tokens(d.tokens)}</td>
                  <td className="num">{d.turnos}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {custos.conversas_mais_caras.length > 0 && (
        <section>
          <h3>Conversas mais caras</h3>
          <ol className="caras">
            {custos.conversas_mais_caras.map((c) => (
              <li key={c.id}>
                <Link to={`/conversas/${c.id}`}>{c.telefone ?? c.canal}</Link>
                <span>{dolar(c.custo_usd)}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </section>
  );
}
