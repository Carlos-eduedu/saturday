import { Link, Navigate, useNavigate, useParams } from "react-router";
import type { Eu } from "../api";
import { Abas, idAba } from "../componentes/Abas";
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
  const navegar = useNavigate();
  const atual = BANCOS.find((b) => b.id === banco);
  if (!atual) return <Navigate to={`/bancos/${BANCOS[0].id}`} replace />;

  return (
    <div className="bancos">
      <h1 className="titulo-tela">Bancos</h1>
      <Abas
        rotulo="Bancos"
        painel="banco-painel"
        opcoes={BANCOS.map((b): [Banco["id"], string] => [b.id, b.nome])}
        valor={atual.id}
        mudar={(id) => navegar(`/bancos/${id}`)}
      />
      <div
        role="tabpanel"
        id="banco-painel"
        aria-labelledby={idAba("banco-painel", atual.id)}
        className="painel-aba"
      >
        <header className="banco-cabeca">
          <h2>
            {atual.nome} <span className="contagem">· {atual.produto}</span>
          </h2>
          <span className={`selo ${SELO[atual.situacao]}`}>{atual.situacao}</span>
          {atual.regras && (
            <Link to={`/operacao#${atual.regras}`}>Ver as regras vigentes na Operação</Link>
          )}
        </header>
        {atual.id === "granatech" ? <Granatech eu={eu} /> : <Leitura banco={atual} />}
      </div>
    </div>
  );
}

// Banco sem integração por API: o que o agente já faz com ele e o que falta.
function Leitura({ banco }: { banco: Banco }) {
  return (
    <section className="banco-leitura">
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
    </section>
  );
}
