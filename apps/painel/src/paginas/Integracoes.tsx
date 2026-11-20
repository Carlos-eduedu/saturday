import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import {
  api,
  type EntregaIntegracao,
  type EscopoIntegracao,
  type Integracao,
  mensagemDeFalha,
  type Parceiro,
} from "../api";
import { Abas, idAba } from "../componentes/Abas";
import { useConfirmar } from "../componentes/Confirmar";
import { Dialogo } from "../componentes/Dialogo";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { relativo, rotulo, SITUACAO_DA_CONSULTA, SITUACAO_DA_PROPOSTA } from "../rotulos";
import { useAcao } from "../useAcao";

// Tela Integrações, só para gestor, em duas abas:
// - Parceiros: os serviços que o Saturday chama, só leitura. Dos segredos o
//   servidor manda só se estão configurados (regra 8).
// - Tokens de acesso (decisão 0035): tokens de sistemas de fora (o APP MEX) no
//   proxy da Granatech. O token aparece uma vez, logo depois de criado; o
//   servidor guarda só o hash. Revogar é para sempre. Cada token pode ter um
//   webhook, que recebe o status novo das consultas e propostas que ele abriu,
//   assinado com um segredo que também aparece uma vez.

const ABAS: ["parceiros" | "tokens", string][] = [
  ["parceiros", "Parceiros"],
  ["tokens", "Tokens de acesso"],
];

const ESCOPOS: { valor: EscopoIntegracao; rotulo: string; texto: string }[] = [
  { valor: "leitura", rotulo: "Leitura", texto: "consultas, propostas, bancos e cota" },
  { valor: "revelar", rotulo: "Revelar CPF", texto: "CPF completo de uma consulta, auditado" },
  { valor: "acoes", rotulo: "Ações", texto: "cancelar e corrigir a conta" },
  { valor: "operacoes", rotulo: "Operações", texto: "abrir consulta, simular e criar proposta" },
  { valor: "homologacao", rotulo: "Homologação", texto: "rodadas de homologação" },
];
const ROTULO_ESCOPO = Object.fromEntries(ESCOPOS.map((e) => [e.valor, e.rotulo]));

export function Integracoes() {
  const { aba } = useParams();
  const navegar = useNavigate();
  if (aba !== "parceiros" && aba !== "tokens")
    return <Navigate to="/integracoes/parceiros" replace />;

  return (
    <div className="integracoes tela-compacta">
      <h1 className="titulo-tela">Integrações</h1>
      <Abas
        rotulo="Integrações"
        painel="integracoes-painel"
        opcoes={ABAS}
        valor={aba}
        mudar={(v) => navegar(`/integracoes/${v}`)}
      />
      <div
        role="tabpanel"
        id="integracoes-painel"
        aria-labelledby={idAba("integracoes-painel", aba)}
        className="painel-aba"
      >
        {aba === "parceiros" ? <Parceiros /> : <Tokens />}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ parceiros

const SELO_PARCEIRO: Record<Parceiro["situacao"], [string, string]> = {
  ligado: ["Ligado", "selo-ia"],
  desligado: ["Desligado", "selo-desligado"],
  falta_chave: ["Falta chave", "selo-handoff"],
};

function Parceiros() {
  const [lista, setLista] = useState<Parceiro[] | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(() => {
    setErro("");
    api
      .parceiros()
      .then(setLista)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, []);
  useEffect(carregar, [carregar]);

  if (!lista)
    return erro ? (
      <Falha titulo="Não deu para carregar os parceiros." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <>
      <p className="nota">
        Serviços que o Saturday chama. As chaves ficam no servidor: aqui só aparece se estão
        configuradas.
      </p>
      <ul className="grade-parceiros">
        {lista.map((p) => {
          const [texto, classe] =
            p.sempre && p.situacao === "ligado" ? ["Sempre ligado", "selo-ia"] : SELO_PARCEIRO[p.situacao];
          const faltam = Object.entries(p.segredos)
            .filter(([, ok]) => !ok)
            .map(([nome]) => nome.replaceAll("_", " "));
          return (
            <li key={p.id} className="parceiro">
              <header>
                <h2>{p.nome}</h2>
                <span className={`selo ${classe}`}>{texto}</span>
              </header>
              <p>{p.descricao}</p>
              {p.host && <code className="dado">{p.host}</code>}
              {p.situacao === "falta_chave" && (
                <p className="aviso">Sem {faltam.join(", ")} no servidor.</p>
              )}
              {p.em_canais && <Link to="/canais">Ver em Canais</Link>}
            </li>
          );
        })}
      </ul>
    </>
  );
}

// ------------------------------------------------------------------ tokens

function Tokens() {
  const [lista, setLista] = useState<Integracao[] | null>(null);
  const [criando, setCriando] = useState(false);
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
      <Falha titulo="Não deu para carregar os tokens." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  const comWebhook = lista.find((i) => i.id === webhookDe && !i.revogada_em);
  return (
    <>
      <div className="cabeca-secao">
        <p className="nota">
          Tokens de sistemas de fora no proxy da Granatech. Cada consulta aberta por eles gasta a
          mesma cota do agente.
        </p>
        <button type="button" className="principal" onClick={() => setCriando(true)}>
          Novo token
        </button>
      </div>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      <section>
        <TabelaIntegracoes lista={lista} agir={agir} abrir={setWebhookDe} />
      </section>
      {criando && <NovaIntegracao recarregar={carregar} fechar={() => setCriando(false)} />}
      {comWebhook && (
        <PainelWebhook
          key={comWebhook.id}
          integracao={comWebhook}
          recarregar={carregar}
          fechar={() => setWebhookDe(null)}
        />
      )}
    </>
  );
}

function TabelaIntegracoes({
  lista,
  agir,
  abrir,
}: {
  lista: Integracao[];
  agir: (acao: () => Promise<unknown>) => Promise<unknown>;
  abrir: (id: string) => void;
}) {
  const confirmar = useConfirmar();
  if (lista.length === 0)
    return <Vazio titulo="Nenhum token." texto="Crie o primeiro em Novo token." />;

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
            <td data-rotulo="Webhook">{i.webhook_url ? hostDe(i.webhook_url) : "—"}</td>
            <td className="acoes">
              {!i.revogada_em && (
                <button type="button" onClick={() => abrir(i.id)}>
                  Webhook
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

// Modal de criar: nome e escopos; criado, o próprio modal mostra o token uma vez.
function NovaIntegracao({ recarregar, fechar }: { recarregar: () => void; fechar: () => void }) {
  const [nome, setNome] = useState("");
  const [escopos, setEscopos] = useState<EscopoIntegracao[]>(["leitura"]);
  const [criada, setCriada] = useState<{ nome: string; token: string } | null>(null);
  const { agir, erro } = useAcao(recarregar);

  function criar(evento: FormEvent) {
    evento.preventDefault();
    const escolhido = nome.trim();
    if (escolhido.length < 2 || escopos.length === 0) return;
    agir(async () => {
      const nova = await api.criarIntegracao(escolhido, escopos);
      setCriada({ nome: nova.nome, token: nova.token });
    });
  }

  const alternar = (valor: EscopoIntegracao) =>
    setEscopos((atuais) =>
      atuais.includes(valor) ? atuais.filter((e) => e !== valor) : [...atuais, valor],
    );

  if (criada)
    return (
      <Dialogo titulo={`Token de ${criada.nome}`} aoFechar={fechar} travado>
        <Revelado
          valor={criada.token}
          aviso="Copie agora: ele não aparece de novo. Se perder, revogue e crie outro."
          fechar={fechar}
        />
      </Dialogo>
    );

  return (
    <Dialogo
      titulo="Novo token"
      aoFechar={fechar}
      rodape={
        <>
          <button type="button" onClick={fechar}>
            Cancelar
          </button>
          <button
            type="submit"
            form="nova-integracao"
            className="principal"
            disabled={escopos.length === 0}
          >
            Criar token
          </button>
        </>
      }
    >
      <form id="nova-integracao" onSubmit={criar} className="nova-integracao">
        {erro && (
          <p className="erro" role="alert">
            {erro}
          </p>
        )}
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
      </form>
    </Dialogo>
  );
}

// Token ou segredo recém-gerado: aparece uma vez, dentro do modal.
// Sem `role="status"`: o leitor de tela leria o valor em voz alta.
function Revelado({ valor, aviso, fechar }: { valor: string; aviso: string; fechar: () => void }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div className="token-novo">
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
    </div>
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
  recarregar,
  fechar,
}: {
  integracao: Integracao;
  recarregar: () => void;
  fechar: () => void;
}) {
  const [url, setUrl] = useState(integracao.webhook_url ?? "");
  const [entregas, setEntregas] = useState<EntregaIntegracao[] | null>(null);
  const [segredo, setSegredo] = useState<string | null>(null);
  const { agir, erro } = useAcao(recarregar);
  const confirmar = useConfirmar();
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
      setSegredo((await api.gerarSegredo(integracao.id)).segredo);
    });
  }

  if (segredo)
    return (
      // `key` distinta: o X fecha o <dialog> nativo, e a volta ao webhook
      // precisa de outro elemento, aberto de novo pelo `showModal`.
      <Dialogo
        key="segredo"
        titulo={`Segredo do webhook de ${integracao.nome}`}
        aoFechar={() => setSegredo(null)}
        travado
      >
        <Revelado
          valor={segredo}
          aviso="Copie agora: ele não aparece de novo. Com ele o sistema confere a assinatura."
          fechar={() => setSegredo(null)}
        />
      </Dialogo>
    );

  const agora = Date.now();
  return (
    <Dialogo key="webhook" titulo={`Webhook de ${integracao.nome}`} aoFechar={fechar} largo>
      <p className="nota">
        Recebe o status novo das consultas e propostas abertas por este token, assinado no
        cabeçalho <code>X-Saturday-Signature</code>. O CPF vai mascarado.
      </p>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
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
        {!integracao.tem_segredo && <span className="aviso">Sem segredo, nenhum aviso sai.</span>}
      </div>
      <h3>Últimas entregas</h3>
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
    </Dialogo>
  );
}
