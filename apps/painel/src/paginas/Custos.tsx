import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type Custos as DadosCustos, ErroApi } from "../api";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { dolar, tokens } from "../rotulos";

// Tela Custos, só para gestor: gasto com IA (OpenRouter) em US$, por dia do mês.
export function Custos() {
  const [custos, setCustos] = useState<DadosCustos | null>(null);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    setErro("");
    api
      .custos()
      .then(setCustos)
      .catch((e: unknown) => setErro(e instanceof ErroApi ? e.message : "falha ao carregar"));
  }, []);
  useEffect(carregar, [carregar]);

  if (erro) return <Falha titulo="Não deu para carregar os custos." texto={erro} aoTentar={carregar} />;
  if (!custos) return <p className="centro">Carregando…</p>;

  const dia = (iso: string) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

  return (
    <div className="custos">
      <h1 className="titulo-tela">
        Custos{" "}
        <span className="contagem">
          · IA em US$, de {dia(custos.de)} a {dia(custos.ate)}
        </span>
      </h1>
      <dl className="totais">
        <div>
          <dt>Hoje</dt>
          <dd>{dolar(custos.hoje?.custo_usd ?? 0)}</dd>
          <dd className="nota">
            {tokens(custos.hoje?.tokens ?? 0)} tokens · {custos.hoje?.turnos ?? 0} turnos
          </dd>
        </div>
        <div>
          <dt>No período</dt>
          <dd>{dolar(custos.total.custo_usd)}</dd>
          <dd className="nota">
            {tokens(custos.total.tokens)} tokens · {custos.total.turnos} turnos
          </dd>
        </div>
        <div>
          <dt>Por turno, em média</dt>
          <dd>{dolar(custos.total.turnos ? custos.total.custo_usd / custos.total.turnos : 0)}</dd>
        </div>
      </dl>

      <section>
        <h2>Por dia</h2>
        {custos.dias.length === 0 ? (
          <Vazio
            titulo="Nenhum turno no período."
            texto="O custo aparece aqui assim que a IA responder."
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
          <h2>Conversas mais caras</h2>
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
    </div>
  );
}
