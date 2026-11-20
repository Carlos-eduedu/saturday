import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  type EntregaIntegracao,
  type EscopoIntegracao,
  type Integracao,
  mensagemDeFalha,
} from "../api";
import { useConfirmar } from "../componentes/Confirmar";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { relativo, rotulo, SITUACAO_DA_CONSULTA, SITUACAO_DA_PROPOSTA } from "../rotulos";
import { useAcao } from "../useAcao";
import { useAoAbrir } from "./Canais";

// Tela Integrações (decisão 0035), só para gestor: tokens de sistemas de fora
// (o APP MEX) no proxy da Granatech. O token aparece uma vez, logo depois de
// criado; o servidor guarda só o hash. Revogar é para sempre. Cada token pode
// ter um webhook, que recebe o status novo das consultas e propostas que ele
// abriu, assinado com um segredo que também aparece uma vez.

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
  const [revelado, setRevelado] = useState<Revelacao | null>(null);
  const [webhookDe, setWebhookDe] = useState<string | null>(null);
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
      {revelado && <Revelado key={revelado.valor} {...revelado} fechar={() => setRevelado(null)} />}
      <section>
        <h2>Tokens</h2>
        <TabelaIntegracoes
          lista={lista}
          agir={agir}
          aberta={webhookDe}
          abrir={(id) => setWebhookDe(id === webhookDe ? null : id)}
        />
        {/* Abre logo abaixo da tabela, perto de quem clicou, como em Canais. */}
        {webhookDe && lista.some((i) => i.id === webhookDe && !i.revogada_em) && (
          <PainelWebhook
            key={webhookDe}
            integracao={lista.find((i) => i.id === webhookDe) as Integracao}
            agir={agir}
            revelar={setRevelado}
            fechar={() => {
              // O painel some com o foco dentro: ele volta ao botão que o abriu.
              document.querySelector<HTMLElement>(`[data-webhook="${webhookDe}"]`)?.focus();
              setWebhookDe(null);
            }}
          />
        )}
      </section>
      <section>
        <NovaIntegracao
          agir={agir}
          criada={(nome, token) =>
            setRevelado({
              titulo: `Token de ${nome}`,
              valor: token,
              aviso: "Copie agora: ele não aparece de novo. Se perder, revogue e crie outro.",
            })
          }
        />
      </section>
    </div>
  );
}

function TabelaIntegracoes({
  lista,
  agir,
  aberta,
  abrir,
}: {
  lista: Integracao[];
  agir: (acao: () => Promise<unknown>) => Promise<unknown>;
  aberta: string | null;
  abrir: (id: string) => void;
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
          <th>Webhook</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {lista.map((i) => (
          <tr
            key={i.id}
            className={i.revogada_em ? "revogada" : aberta === i.id ? "aberta" : undefined}
          >
            <td>
              {i.nome}
              {i.revogada_em && <span className="nota"> · revogada</span>}
            </td>
            <td data-rotulo="Escopos">{i.escopos.map((e) => ROTULO_ESCOPO[e] ?? e).join(", ")}</td>
            <td data-rotulo="Criada por">{i.criada_por ?? "—"}</td>
            <td data-rotulo="Último uso">
              {i.ultimo_uso_em ? relativo(i.ultimo_uso_em, agora) : "nunca"}
            </td>
            <td data-rotulo="Webhook">{i.webhook_url ? hostDe(i.webhook_url) : "—"}</td>
            <td className="acoes">
              {!i.revogada_em && (
                <button
                  type="button"
                  data-webhook={i.id}
                  aria-expanded={aberta === i.id}
                  onClick={() => abrir(i.id)}
                >
                  {aberta === i.id ? "Fechar webhook" : "Webhook"}
                </button>
              )}
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

type Revelacao = { titulo: string; valor: string; aviso: string };

// Token ou segredo recém-gerado: aparece uma vez, no topo, e a tela vai até ele.
function Revelado({ titulo, valor, aviso, fechar }: Revelacao & { fechar: () => void }) {
  const [copiado, setCopiado] = useState(false);
  const topo = useAoAbrir();
  return (
    // Sem `role="status"`: o leitor de tela leria o valor em voz alta. O foco vai ao título.
    <section className="token-novo" aria-label={titulo}>
      <h2 ref={topo} tabIndex={-1}>
        {titulo}
      </h2>
      <p className="aviso">{aviso}</p>
      <code className="dado">{valor}</code>
      <div className="acoes-form">
        <button
          type="button"
          onClick={() =>
            navigator.clipboard.writeText(valor).then(
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

function hostDe(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

const SITUACAO_ENTREGA: Record<EntregaIntegracao["situacao"], string> = {
  entregue: "entregue",
  pendente: "na fila",
  desistiu: "não entregue",
};

function PainelWebhook({
  integracao,
  agir,
  revelar,
  fechar,
}: {
  integracao: Integracao;
  agir: (acao: () => Promise<unknown>) => Promise<unknown>;
  revelar: (r: Revelacao) => void;
  fechar: () => void;
}) {
  const [url, setUrl] = useState(integracao.webhook_url ?? "");
  const [entregas, setEntregas] = useState<EntregaIntegracao[] | null>(null);
  const confirmar = useConfirmar();
  const topo = useAoAbrir();
  useEffect(() => {
    api
      .entregasIntegracao(integracao.id)
      .then(setEntregas)
      .catch(() => setEntregas([]));
  }, [integracao.id]);

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agir(() => api.definirWebhook(integracao.id, url.trim() || null));
  }

  async function gerar() {
    if (
      integracao.tem_segredo &&
      !(await confirmar({
        titulo: `Trocar o segredo do webhook de ${integracao.nome}?`,
        texto:
          "O segredo atual para de valer na hora: os avisos seguintes saem assinados com o novo, " +
          "e o sistema que recebe precisa ser atualizado.",
        acao: "Trocar o segredo",
        perigo: true,
      }))
    )
      return;
    agir(async () => {
      const { segredo } = await api.gerarSegredo(integracao.id);
      revelar({
        titulo: `Segredo do webhook de ${integracao.nome}`,
        valor: segredo,
        aviso: "Copie agora: ele não aparece de novo. Com ele o sistema confere a assinatura.",
      });
    });
  }

  const agora = Date.now();
  return (
    <div className="painel-instancia painel-webhook">
      <div className="painel-topo">
        <h3 ref={topo} tabIndex={-1}>
          Webhook de {integracao.nome}
        </h3>
        <button type="button" onClick={fechar}>
          Fechar
        </button>
      </div>
      <p className="nota">
        Recebe o status novo das consultas e propostas abertas por este token, assinado no
        cabeçalho <code>X-Saturday-Signature</code>. O CPF vai mascarado.
      </p>
      <form onSubmit={salvar} className="nova-instancia endereco-webhook">
        <label>
          Endereço
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://app.mex.com.br/avisos"
          />
        </label>
        <button type="submit">{url.trim() ? "Salvar endereço" : "Tirar o webhook"}</button>
      </form>
      <div className="acoes-form">
        <button type="button" onClick={gerar}>
          {integracao.tem_segredo ? "Trocar o segredo" : "Gerar o segredo"}
        </button>
        {!integracao.tem_segredo && (
          <span className="aviso">Sem segredo, nenhum aviso sai.</span>
        )}
      </div>
      <h4>Últimas entregas</h4>
      {entregas === null ? (
        <p className="nota">Carregando…</p>
      ) : entregas.length === 0 ? (
        <p className="vazio">Nenhum aviso ainda.</p>
      ) : (
        <ul className="lista-numeros">
          {entregas.map((e) => (
            <li key={e.id}>
              <span className="dado">{relativo(e.criada_em, agora)}</span>
              <span>
                {e.tipo === "consulta" ? "Consulta" : "Proposta"} ·{" "}
                {e.status
                  ? rotulo(
                      e.tipo === "consulta" ? SITUACAO_DA_CONSULTA : SITUACAO_DA_PROPOSTA,
                      e.status,
                    )
                  : "—"}
              </span>
              <span className={`estado-entrega entrega-${e.situacao}`}>
                {SITUACAO_ENTREGA[e.situacao]}
              </span>
              <span className="nota">
                {e.tentativas} tentativa{e.tentativas === 1 ? "" : "s"}
                {e.motivo && ` · ${e.motivo}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
