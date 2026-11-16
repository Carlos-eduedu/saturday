import { Link, Navigate, useParams } from "react-router";
import type { Eu } from "../api";
import { Granatech } from "./Granatech";

// Os bancos do agente, cada um na sua seção: o integrado por API, o que só tem
// cálculo e o que ainda falta integrar. Sem interface `Banco` no código até
// existir o segundo integrado (decisão 0004); os números das regras ficam na
// aba Operação, que os lê do servidor.
const BANCOS = [
  {
    id: "granatech",
    nome: "Granatech",
    produto: "Crédito do Trabalhador (CLT)",
    situacao: "Integrado",
    faz: [],
    falta: [],
    regras: "clt",
  },
  {
    id: "c6",
    nome: "C6",
    produto: "Portabilidade INSS",
    situacao: "Só cálculo",
    faz: [
      "Lê o extrato de empréstimos do Meu INSS que o cliente envia.",
      "Aplica as regras do C6 a cada contrato e calcula a sobra.",
      "Apresenta a oferta e, no aceite, passa a conversa para um atendente.",
    ],
    falta: [
      "Digitar a proposta no C6: hoje quem digita é o atendente.",
      "Acompanhar a proposta depois da digitação (saldo, confirmação no Meu INSS, pagamento).",
    ],
    regras: "portabilidade-inss",
  },
  {
    id: "icred",
    nome: "iCred",
    produto: "INSS: portabilidade, refinanciamento e contrato novo",
    situacao: "A integrar",
    faz: ["Nada ainda. Existe só a pesquisa da API, em docs/icred.md."],
    falta: [
      "Decidir se o iCred entra no escopo do agente.",
      "Chave de acesso à API.",
      "Guardar a prova do consentimento no Saturday: a API recebe só a confirmação.",
      "Cliente da API, recebimento dos avisos e testes com simulador.",
    ],
    regras: null,
  },
] as const;

type Banco = (typeof BANCOS)[number];

const SELO: Record<Banco["situacao"], string> = {
  Integrado: "selo-ia",
  "Só cálculo": "selo-assumida",
  "A integrar": "selo-handoff",
};

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
            <span className={`selo ${SELO[b.situacao]}`}>{b.situacao}</span>
          </Link>
        ))}
      </nav>
      {atual.id === "granatech" ? <Granatech eu={eu} /> : <Leitura banco={atual} />}
    </div>
  );
}

// Banco sem integração por API: o que o agente já faz com ele e o que falta.
function Leitura({ banco }: { banco: Banco }) {
  return (
    <section className="banco-leitura">
      <h2>
        {banco.nome} <span className="contagem">· {banco.produto}</span>
      </h2>
      <div className="banco-leitura__colunas">
        <div>
          <h3>O que o agente faz hoje</h3>
          <ul>
            {banco.faz.map((linha) => (
              <li key={linha}>{linha}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3>O que falta para integrar</h3>
          <ul>
            {banco.falta.map((linha) => (
              <li key={linha}>{linha}</li>
            ))}
          </ul>
        </div>
      </div>
      {banco.regras && (
        <p>
          <Link to={`/operacao#${banco.regras}`}>Ver as regras vigentes na Operação</Link>
        </p>
      )}
    </section>
  );
}
