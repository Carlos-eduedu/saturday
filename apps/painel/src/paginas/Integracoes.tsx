import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, type EscopoIntegracao, type Integracao, mensagemDeFalha } from "../api";
import { useConfirmar } from "../componentes/Confirmar";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { relativo } from "../rotulos";
import { useAcao } from "../useAcao";
import { useAoAbrir } from "./Canais";

// Tela Integrações (decisão 0035), só para gestor: tokens de sistemas de fora
// (o APP MEX) no proxy da Granatech. O token aparece uma vez, logo depois de
// criado; o servidor guarda só o hash. Revogar é para sempre.

const ESCOPOS: { valor: EscopoIntegracao; rotulo: string; texto: string }[] = [
  { valor: "leitura", rotulo: "Leitura", texto: "consultas, propostas, bancos e cota" },
  { valor: "revelar", rotulo: "Revelar CPF", texto: "CPF completo de uma consulta, auditado" },
  { valor: "acoes", rotulo: "Ações", texto: "cancelar e corrigir a conta" },
  { valor: "operacoes", rotulo: "Operações", texto: "abrir consulta, simular e criar proposta" },
  { valor: "homologacao", rotulo: "Homologação", texto: "rodadas de homologação" },
];
const ROTULO_ESCOPO = Object.fromEntries(ESCOPOS.map((e) => [e.valor, e.rotulo]));

export function Integracoes() {
  const [lista, setLista] = useState<Integracao[] | null>(null);
  const [novoToken, setNovoToken] = useState<{ nome: string; token: string } | null>(null);
  const { agir, erro, setErro } = useAcao(() => carregar());
  const carregar = useCallback(() => {
    api
      .integracoes()
      .then(setLista)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, [setErro]);
  useEffect(carregar, [carregar]);

  if (!lista)
    return erro ? (
      <Falha titulo="Não deu para carregar as integrações." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <div className="integracoes">
      <h1 className="titulo-tela">Integrações</h1>
      <p className="nota">
        Tokens de sistemas de fora no proxy da Granatech. Cada consulta aberta por eles gasta a
        mesma cota do agente.
      </p>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {novoToken && (
        <TokenNovo key={novoToken.token} {...novoToken} fechar={() => setNovoToken(null)} />
      )}
      <section>
        <h2>Tokens</h2>
        <TabelaIntegracoes lista={lista} agir={agir} />
      </section>
      <section>
        <NovaIntegracao agir={agir} criada={(nome, token) => setNovoToken({ nome, token })} />
      </section>
    </div>
  );
}

function TabelaIntegracoes({
  lista,
  agir,
}: {
  lista: Integracao[];
  agir: (acao: () => Promise<unknown>) => Promise<unknown>;
}) {
  const confirmar = useConfirmar();
  if (lista.length === 0)
    return <Vazio titulo="Nenhuma integração." texto="Crie o primeiro token abaixo." />;

  const agora = Date.now();
  return (
    <table>
      <thead>
        <tr>
          <th>Nome</th>
          <th>Escopos</th>
          <th>Criada por</th>
          <th>Último uso</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {lista.map((i) => (
          <tr key={i.id} className={i.revogada_em ? "revogada" : undefined}>
            <td>
              {i.nome}
              {i.revogada_em && <span className="nota"> · revogada</span>}
            </td>
            <td data-rotulo="Escopos">{i.escopos.map((e) => ROTULO_ESCOPO[e] ?? e).join(", ")}</td>
            <td data-rotulo="Criada por">{i.criada_por ?? "—"}</td>
            <td data-rotulo="Último uso">
              {i.ultimo_uso_em ? relativo(i.ultimo_uso_em, agora) : "nunca"}
            </td>
            <td className="acoes">
              {!i.revogada_em && (
                <button
                  type="button"
                  className="perigo"
                  onClick={async () =>
                    (await confirmar({
                      titulo: `Revogar o token ${i.nome}?`,
                      texto:
                        "O sistema que usa este token para de acessar na hora. Não dá para desfazer: " +
                        "para voltar, crie um token novo.",
                      acao: "Revogar",
                      perigo: true,
                    })) && agir(() => api.revogarIntegracao(i.id))
                  }
                >
                  Revogar
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NovaIntegracao({
  agir,
  criada,
}: {
  agir: (acao: () => Promise<unknown>) => Promise<unknown>;
  criada: (nome: string, token: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [escopos, setEscopos] = useState<EscopoIntegracao[]>(["leitura"]);

  function criar(evento: FormEvent) {
    evento.preventDefault();
    const escolhido = nome.trim();
    if (escolhido.length < 2 || escopos.length === 0) return;
    agir(async () => {
      const nova = await api.criarIntegracao(escolhido, escopos);
      criada(nova.nome, nova.token);
      setNome("");
      setEscopos(["leitura"]);
    });
  }

  const alternar = (valor: EscopoIntegracao) =>
    setEscopos((atuais) =>
      atuais.includes(valor) ? atuais.filter((e) => e !== valor) : [...atuais, valor],
    );

  return (
    <form onSubmit={criar} className="nova-integracao">
      <h2>Novo token</h2>
      <label>
        Nome
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          minLength={2}
          maxLength={80}
          required
          placeholder="ex.: APP MEX"
        />
      </label>
      <fieldset>
        <legend>Escopos</legend>
        {ESCOPOS.map((e) => (
          <label key={e.valor} className="opcao">
            <input
              type="checkbox"
              checked={escopos.includes(e.valor)}
              onChange={() => alternar(e.valor)}
            />
            {e.rotulo}
            <small className="nota">{e.texto}</small>
          </label>
        ))}
      </fieldset>
      <button type="submit" disabled={escopos.length === 0}>
        Criar token
      </button>
    </form>
  );
}

function TokenNovo({ nome, token, fechar }: { nome: string; token: string; fechar: () => void }) {
  const [copiado, setCopiado] = useState(false);
  // O formulário fica embaixo; o token aparece no topo e a tela vai até ele.
  const topo = useAoAbrir();
  return (
    // Sem `role="status"`: o leitor de tela leria o token em voz alta. O foco vai ao título.
    <section className="token-novo" aria-label={`Token de ${nome}`}>
      <h2 ref={topo} tabIndex={-1}>
        Token de {nome}
      </h2>
      <p className="aviso">
        Copie agora: ele não aparece de novo. Se perder, revogue e crie outro.
      </p>
      <code className="dado">{token}</code>
      <div className="acoes-form">
        <button
          type="button"
          onClick={() =>
            navigator.clipboard.writeText(token).then(
              () => setCopiado(true),
              () => setCopiado(false),
            )
          }
        >
          {copiado ? "Copiado" : "Copiar"}
        </button>
        <button type="button" onClick={fechar}>
          Já guardei
        </button>
      </div>
    </section>
  );
}
