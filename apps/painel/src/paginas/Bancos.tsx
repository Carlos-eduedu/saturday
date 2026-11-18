import { Link, Navigate, useNavigate, useParams } from "react-router";
import type { Eu } from "../api";
import { Abas, idAba } from "../componentes/Abas";
import { Granatech } from "./Granatech";

// Os bancos do agente, cada um na sua seção: o integrado por API e os que o
// agente só simula, consulta e oferece. Sem interface `Banco` no código até
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
    regras: [["clt", "Ver as regras vigentes na Operação"]],
  },
  {
    id: "c6",
    nome: "C6",
    produto: "INSS: portabilidade e contrato novo",
    situacao: "Simulação e oferta",
    faz: [
      "Lê o extrato de empréstimos do Meu INSS que o cliente envia.",
      "Calcula a portabilidade: aplica as regras do C6 a cada contrato e calcula a sobra.",
      "Com o SIM do cliente, simula o contrato novo pela API do C6 e oferece.",
      "No aceite, passa a conversa para um atendente, com as condições.",
    ],
    falta: [
      "Digitar a proposta pela API do C6: hoje quem digita é o atendente.",
      "Refinanciamento de contrato que o cliente já tem no C6.",
      "Acompanhar a proposta depois da digitação.",
      "Credencial própria do Saturday na API do C6.",
    ],
    regras: [
      ["portabilidade-inss", "Regras da portabilidade"],
      ["contrato-novo-inss", "Regras do contrato novo"],
    ],
  },
  {
    id: "icred",
    nome: "iCred",
    produto: "INSS: portabilidade, refinanciamento e contrato novo",
    situacao: "Consulta e oferta",
    faz: [
      "Depois do extrato, pede o SIM e o CPF do cliente e consulta o iCred.",
      "Apresenta a proposta do iCred quando ela põe mais dinheiro na conta do que a portabilidade C6, com taxa de até 1,85% ao mês.",
      "No aceite, guarda a prova e passa a conversa para um atendente gravar a proposta.",
    ],
    falta: [
      "Ligar: cadastrar a chave e o aviso de resultado no motor do iCred.",
      "Gravar a proposta pelo agente: depende de mudanças no motor.",
      "Acompanhar a proposta depois da gravação.",
      "Confirmar se a oferta do iCred tem seguro.",
    ],
    regras: [],
  },
] as const;

type Banco = (typeof BANCOS)[number];

const SELO: Record<Banco["situacao"], string> = {
  Integrado: "selo-ia",
  "Simulação e oferta": "selo-assumida",
  "Consulta e oferta": "selo-assumida",
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
          {/* A aba já diz o banco: o título da seção é o produto. */}
          <h2>{atual.produto}</h2>
          <span className={`selo ${SELO[atual.situacao]}`}>{atual.situacao}</span>
          {atual.regras.map(([produto, texto]) => (
            <Link key={produto} to={`/operacao#${produto}`}>
              {texto}
            </Link>
          ))}
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
