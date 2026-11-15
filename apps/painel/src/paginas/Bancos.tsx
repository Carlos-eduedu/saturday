import { Link, Navigate, useParams } from "react-router";
import type { Eu } from "../api";
import { Granatech } from "./Granatech";

// Os bancos ligados ao agente, cada um na sua seção. Hoje só a Granatech; sem
// interface `Banco` no código até existir o segundo (decisão 0004).
const BANCOS = [{ id: "granatech", nome: "Granatech", produto: "Crédito do Trabalhador (CLT)" }];

export function Bancos({ eu }: { eu: Eu }) {
  const { banco } = useParams();
  const atual = BANCOS.find((b) => b.id === banco);
  if (!atual) return <Navigate to={`/bancos/${BANCOS[0].id}`} replace />;

  return (
    <div className="bancos">
      <h1 className="titulo-tela">Bancos</h1>
      <nav className="bancos-nav" aria-label="Bancos">
        {BANCOS.map((b) => (
          <Link
            key={b.id}
            to={`/bancos/${b.id}`}
            aria-current={b.id === atual.id ? "page" : undefined}
          >
            <strong>{b.nome}</strong>
            <span>{b.produto}</span>
          </Link>
        ))}
      </nav>
      {atual.id === "granatech" && <Granatech eu={eu} />}
    </div>
  );
}
