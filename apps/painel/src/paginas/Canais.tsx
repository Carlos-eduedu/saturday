import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Vazio } from "../componentes/Vazio";
import {
  api,
  type Canais as DadosCanais,
  type ConfiguracoesInstancia,
  type DetalhesInstancia,
  ErroApi,
  type InstanciaEvolution,
  type Qr,
  type RespostaRapida,
} from "../api";
import { Falha } from "../componentes/Falha";

// Tela Canais (decisão 0010), só para gestor: números da Meta para consulta e
// instâncias da Evolution geridas aqui. O QR se renova sozinho até conectar.
// Detalhes mostram o webhook e as configurações gravados na Evolution, lado a
// lado com o que o Saturday aplica; o token nunca chega ao navegador. O gestor
// regrava o webhook e ajusta as configurações aqui (decisão 0011).

const RENOVAR_QR_MS = 5000;

const ROTULO_ESTADO: Record<string, string> = {
  open: "conectada",
  connecting: "aguardando QR",
  close: "desconectada",
  refused: "QR esgotado",
};

const ROTULO_AUTENTICACAO: Record<DetalhesInstancia["webhook"]["autenticacao"], string> = {
  confere: "token confere",
  diferente: "token diferente",
  ausente: "sem token",
};

// O que cada configuração da Evolution faz, para quem lê a tela.
const ROTULO_CONFIGURACAO: Record<string, string> = {
  rejectCall: "Recusar chamadas",
  groupsIgnore: "Ignorar grupos",
  alwaysOnline: "Sempre online",
  readMessages: "Marcar mensagens como lidas",
  readStatus: "Ler status (stories)",
  syncFullHistory: "Sincronizar histórico completo",
};

function simNao(valor: boolean | null): string {
  return valor === null ? "—" : valor ? "sim" : "não";
}

function mensagemDe(erro: unknown): string {
  return erro instanceof ErroApi ? erro.message : "falha inesperada";
}

export function Canais() {
  const [canais, setCanais] = useState<DadosCanais | null>(null);
  const [erro, setErro] = useState("");
  const [qrDe, setQrDe] = useState<{ nome: string; qr: Qr } | null>(null);
  const [detalhesDe, setDetalhesDe] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .canais()
      .then(setCanais)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, []);
  useEffect(carregar, [carregar]);

  async function agir(acao: () => Promise<unknown>) {
    setErro("");
    try {
      await acao();
    } catch (e) {
      setErro(mensagemDe(e));
    }
    carregar();
  }

  if (!canais)
    return erro ? (
      <Falha titulo="Não deu para carregar os canais." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <div className="canais">
      <h1 className="titulo-tela">Canais</h1>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}

      <section>
        <h2>Evolution (WhatsApp Web)</h2>
        {!canais.evolution.ativo ? (
          <p className="vazio">Canal desligado (SATURDAY_EVOLUTION_ATIVO).</p>
        ) : (
          <>
            {canais.evolution.erro && (
              <p className="erro" role="alert">
                {canais.evolution.erro}
              </p>
            )}
            <TabelaInstancias
              instancias={canais.evolution.instancias}
              agir={agir}
              mostrarQr={(nome, qr) => {
                setDetalhesDe(null);
                setQrDe({ nome, qr });
              }}
              aberta={detalhesDe}
              detalhar={(nome) => {
                setQrDe(null);
                setDetalhesDe(nome === detalhesDe ? null : nome);
              }}
            />
            <NovaInstancia
              agir={agir}
              mostrarQr={(nome, qr) => {
                setDetalhesDe(null);
                setQrDe({ nome, qr });
              }}
            />
            {/* Abrem junto da tabela, perto de quem clicou, e não no fim da página. */}
            {qrDe && (
              <PainelQr
                key={qrDe.nome}
                nome={qrDe.nome}
                inicial={qrDe.qr}
                fechar={() => {
                  setQrDe(null);
                  carregar();
                }}
              />
            )}
            {detalhesDe && (
              <PainelDetalhes
                key={detalhesDe}
                nome={detalhesDe}
                fechar={() => setDetalhesDe(null)}
              />
            )}
          </>
        )}
      </section>

      <section>
        <h2>WhatsApp oficial (Meta)</h2>
        <p className="nota">Só leitura: os números da Meta são configurados no Meta Business.</p>
        {canais.meta.length === 0 ? (
          <p className="vazio">Nenhum número configurado.</p>
        ) : (
          <ul>
            {canais.meta.map((m) => (
              <li key={m.phone_number_id}>
                <code>{m.phone_number_id}</code>
              </li>
            ))}
          </ul>
        )}
      </section>

      <RespostasRapidas />
    </div>
  );
}

function TabelaInstancias({
  instancias,
  agir,
  mostrarQr,
  aberta,
  detalhar,
}: {
  instancias: InstanciaEvolution[];
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mostrarQr: (nome: string, qr: Qr) => void;
  aberta: string | null;
  detalhar: (nome: string) => void;
}) {
  if (instancias.length === 0)
    return (
      <Vazio titulo="Nenhuma instância." texto="Crie a primeira abaixo e leia o QR no celular." />
    );

  function confirmar(verbo: string, i: InstanciaEvolution): boolean {
    return window.confirm(
      `${verbo} a instância ${i.nome}? ${i.conversas_7_dias} conversa(s) falaram por ela nos ` +
        "últimos 7 dias; as respostas pendentes para elas não serão entregues.",
    );
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Instância</th>
          <th>Estado</th>
          <th>Telefone</th>
          <th>Conversas (7 dias)</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {instancias.map((i) => (
          <tr key={i.nome} className={aberta === i.nome ? "aberta" : undefined}>
            <td>{i.nome}</td>
            <td data-rotulo="Estado">
              <span className={`estado-instancia estado-${i.estado}`}>
                {ROTULO_ESTADO[i.estado] ?? i.estado}
              </span>
            </td>
            <td data-rotulo="Telefone">{i.telefone || "—"}</td>
            <td data-rotulo="Conversas (7 dias)">{i.conversas_7_dias}</td>
            <td className="acoes">
              <button
                type="button"
                aria-expanded={aberta === i.nome}
                onClick={() => detalhar(i.nome)}
              >
                {aberta === i.nome ? "Fechar detalhes" : "Detalhes"}
              </button>
              {i.estado !== "open" && (
                <button
                  type="button"
                  onClick={() =>
                    agir(async () => mostrarQr(i.nome, await api.conectarInstancia(i.nome)))
                  }
                >
                  Reconectar
                </button>
              )}
              {i.estado === "open" && (
                <button
                  type="button"
                  onClick={() =>
                    confirmar("Desconectar", i) && agir(() => api.desconectarInstancia(i.nome))
                  }
                >
                  Desconectar
                </button>
              )}
              <button
                type="button"
                className="perigo"
                onClick={() => confirmar("Apagar", i) && agir(() => api.apagarInstancia(i.nome))}
              >
                Apagar
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NovaInstancia({
  agir,
  mostrarQr,
}: {
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mostrarQr: (nome: string, qr: Qr) => void;
}) {
  const [nome, setNome] = useState("");

  function criar(evento: FormEvent) {
    evento.preventDefault();
    const escolhido = nome.trim();
    if (!escolhido) return;
    agir(async () => {
      mostrarQr(escolhido, await api.criarInstancia(escolhido));
      setNome("");
    });
  }

  return (
    <form onSubmit={criar} className="nova-instancia">
      <label>
        Nova instância
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          pattern="[a-z0-9-]{3,32}"
          title="De 3 a 32 letras minúsculas, números ou hífen"
          placeholder="ex.: mex-atendimento"
        />
      </label>
      <button type="submit">Criar e mostrar QR</button>
    </form>
  );
}

function PainelQr({ nome, inicial, fechar }: { nome: string; inicial: Qr; fechar: () => void }) {
  const [qr, setQr] = useState<Qr>(inicial);
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (qr.estado === "open") return;
    const id = window.setInterval(() => {
      api
        .qrInstancia(nome)
        .then(setQr)
        .catch((e: unknown) => setErro(mensagemDe(e)));
    }, RENOVAR_QR_MS);
    return () => window.clearInterval(id);
  }, [nome, qr.estado]);

  const topo = useAoAbrir();
  return (
    <section className="painel-instancia qr" aria-live="polite">
      <div className="painel-topo">
        <h3 ref={topo} tabIndex={-1}>
          Conectar {nome}
        </h3>
        <button type="button" onClick={fechar}>
          Fechar
        </button>
      </div>
      {qr.estado === "open" ? (
        <p>Conectada. O telefone fica fixado nesta instância.</p>
      ) : qr.qr ? (
        <>
          <p>No celular: WhatsApp, Aparelhos conectados, Conectar um aparelho.</p>
          <img src={qr.qr} alt={`QR para conectar a instância ${nome}`} width={264} height={264} />
        </>
      ) : (
        <p className="aviso">QR indisponível. Feche e clique em Reconectar.</p>
      )}
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
    </section>
  );
}

// Leva quem clicou até o painel que abriu e põe o foco no título dele.
function useAoAbrir() {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const titulo = ref.current;
    if (!titulo) return;
    const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    titulo.scrollIntoView({ behavior: suave ? "smooth" : "auto", block: "start" });
    titulo.focus({ preventScroll: true });
  }, []);
  return ref;
}

function PainelDetalhes({ nome, fechar }: { nome: string; fechar: () => void }) {
  const [detalhes, setDetalhes] = useState<DetalhesInstancia | null>(null);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");

  const carregar = useCallback(() => {
    api
      .detalhesInstancia(nome)
      .then(setDetalhes)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, [nome]);
  useEffect(carregar, [carregar]);

  async function agir(acao: () => Promise<unknown>, feito: string) {
    setErro("");
    setAviso("");
    try {
      await acao();
      setAviso(feito);
    } catch (e) {
      setErro(mensagemDe(e));
    }
    carregar();
  }

  const topo = useAoAbrir();
  return (
    <section className="painel-instancia detalhes-instancia" aria-live="polite">
      <div className="painel-topo">
        <h3 ref={topo} tabIndex={-1}>
          Detalhes de {nome}
        </h3>
        <button type="button" onClick={fechar}>
          Fechar
        </button>
      </div>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="confere">{aviso}</p>}
      {!detalhes && !erro && <p className="nota">Consultando a Evolution…</p>}
      {detalhes && (
        <>
          <SecaoWebhook
            detalhes={detalhes}
            reaplicar={() => agir(() => api.reaplicarWebhook(nome), "Webhook do Saturday regravado.")}
          />
          <FormEventos
            key={detalhes.webhook.eventos.join()}
            detalhes={detalhes}
            salvar={(eventos) =>
              agir(() => api.escolherEventos(nome, eventos), "Eventos salvos na Evolution.")
            }
          />
          <FormConfiguracoes
            key={JSON.stringify(detalhes.configuracoes) + detalhes.mensagem_chamada}
            detalhes={detalhes}
            salvar={(valores) =>
              agir(() => api.configurarInstancia(nome, valores), "Configurações salvas na Evolution.")
            }
          />
        </>
      )}
    </section>
  );
}

function SecaoWebhook({
  detalhes,
  reaplicar,
}: {
  detalhes: DetalhesInstancia;
  reaplicar: () => void;
}) {
  const { webhook, divergencias } = detalhes;

  return (
    <div className="grupo-detalhes">
      <h4>Webhook</h4>
      {divergencias.length === 0 ? (
        <p className="confere">O webhook confere com o do Saturday.</p>
      ) : (
        <div className="divergencias" role="status">
          <p>{divergencias.length} diferença(s) em relação ao webhook do Saturday:</p>
          <ul>
            {divergencias.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
          <button type="button" onClick={reaplicar}>
            Regravar o webhook do Saturday
          </button>
          <p className="nota">Não desconecta a instância.</p>
        </div>
      )}

      {webhook.configurado && (
        <dl className="campos">
          <dt>Ligado</dt>
          <dd>{simNao(webhook.ativo)}</dd>
          <dt>URL</dt>
          <dd>
            <code>{webhook.url || "—"}</code>
            {webhook.url !== webhook.url_esperada && (
              <small className="esperado">
                esperada: <code>{webhook.url_esperada}</code>
              </small>
            )}
          </dd>
          <dt>Autenticação</dt>
          <dd>{ROTULO_AUTENTICACAO[webhook.autenticacao]}</dd>
          <dt>URL por evento</dt>
          <dd>{simNao(webhook.por_evento)}</dd>
          <dt>Mídia em base64</dt>
          <dd>{simNao(webhook.base64)}</dd>
        </dl>
      )}
    </div>
  );
}

function FormEventos({
  detalhes,
  salvar,
}: {
  detalhes: DetalhesInstancia;
  salvar: (eventos: string[]) => void;
}) {
  const { eventos, eventos_esperados: doSaturday, eventos_disponiveis } = detalhes.webhook;
  const inicial = eventos.filter((e) => !doSaturday.includes(e));
  const [extras, setExtras] = useState<string[]>(inicial);
  const mudou = [...extras].sort().join() !== [...inicial].sort().join();
  const faltando = doSaturday.filter((e) => !eventos.includes(e));
  const outros = eventos_disponiveis.filter((e) => !doSaturday.includes(e));

  function alternar(evento: string, ligado: boolean) {
    setExtras(ligado ? [...extras, evento] : extras.filter((e) => e !== evento));
  }

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    salvar(extras);
  }

  return (
    <form className="configuracoes grupo-detalhes" onSubmit={enviar}>
      <h4>Eventos</h4>
      <fieldset>
        <legend>Usados pelo Saturday (sempre ligados)</legend>
        <div className="grade-eventos">
          {doSaturday.map((e) => (
            <label key={e} className="opcao">
              <input type="checkbox" checked disabled />
              <code>{e}</code>
              {faltando.includes(e) && <small className="evento-falta">falta na instância</small>}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Outros eventos</legend>
        <p className="nota">
          Chegam ao webhook, mas o Saturday ainda não faz nada com eles: ligue só o que for usar.
        </p>
        <div className="grade-eventos">
          {outros.map((e) => (
            <label key={e} className="opcao">
              <input
                type="checkbox"
                checked={extras.includes(e)}
                onChange={(ev) => alternar(e, ev.target.checked)}
              />
              <code>{e}</code>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="acoes-form">
        <button type="submit" disabled={!mudou && faltando.length === 0}>
          Salvar eventos na Evolution
        </button>
      </div>
    </form>
  );
}

type Booleanas = Exclude<keyof ConfiguracoesInstancia, "msgCall">;

function FormConfiguracoes({
  detalhes,
  salvar,
}: {
  detalhes: DetalhesInstancia;
  salvar: (valores: ConfiguracoesInstancia) => void;
}) {
  const padrao = Object.fromEntries(
    detalhes.configuracoes.map((c) => [c.nome, c.padrao]),
  ) as Record<Booleanas, boolean>;
  const inicial: ConfiguracoesInstancia = {
    ...padrao,
    ...Object.fromEntries(
      detalhes.configuracoes.filter((c) => c.atual !== null).map((c) => [c.nome, c.atual]),
    ),
    msgCall: detalhes.mensagem_chamada,
  };
  const [valores, setValores] = useState<ConfiguracoesInstancia>(inicial);
  const mudou = JSON.stringify(valores) !== JSON.stringify(inicial);

  if (detalhes.configuracoes.length === 0)
    return (
      <div className="grupo-detalhes">
        <h4>Configurações da instância</h4>
        <p className="vazio">A Evolution não devolveu configurações.</p>
      </div>
    );

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    salvar(valores);
  }

  return (
    <form className="configuracoes grupo-detalhes" onSubmit={enviar}>
      <h4>Configurações da instância</h4>
      <div className="grade-eventos">
      {detalhes.configuracoes.map((c) => {
        const nome = c.nome as Booleanas;
        return (
          <label key={nome} className="opcao">
            <input
              type="checkbox"
              checked={valores[nome]}
              onChange={(e) => setValores({ ...valores, [nome]: e.target.checked })}
            />
            <span>
              {ROTULO_CONFIGURACAO[nome] ?? nome}
              {valores[nome] !== c.padrao && (
                <small className="esperado"> padrão do Saturday: {simNao(c.padrao)}</small>
              )}
            </span>
          </label>
        );
      })}
      </div>
      {valores.rejectCall && (
        <label>
          Mensagem para quem ligar (opcional)
          <textarea
            value={valores.msgCall}
            maxLength={500}
            rows={2}
            onChange={(e) => setValores({ ...valores, msgCall: e.target.value })}
          />
        </label>
      )}
      <div className="acoes-form">
        <button type="submit" disabled={!mudou}>
          Salvar na Evolution
        </button>
        <button type="button" onClick={() => setValores({ ...valores, ...padrao })}>
          Usar o padrão do Saturday
        </button>
      </div>
    </form>
  );
}

// Textos salvos que a equipe insere na conversa com "/atalho". Só o gestor
// mantém; o texto é fixo e quem envia revisa antes.
function RespostasRapidas() {
  const [lista, setLista] = useState<RespostaRapida[] | null>(null);
  const [editando, setEditando] = useState<RespostaRapida | null>(null);
  const [atalho, setAtalho] = useState("");
  const [texto, setTexto] = useState("");
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    api
      .respostas()
      .then(setLista)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, []);
  useEffect(carregar, [carregar]);

  function editar(r: RespostaRapida | null) {
    setEditando(r);
    setAtalho(r?.atalho ?? "");
    setTexto(r?.texto ?? "");
    setErro("");
  }

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    const dados = { atalho: atalho.trim().toLowerCase(), texto: texto.trim() };
    try {
      await (editando ? api.editarResposta(editando.id, dados) : api.criarResposta(dados));
      editar(null);
      carregar();
    } catch (e) {
      setErro(mensagemDe(e));
    }
  }

  async function apagar(r: RespostaRapida) {
    if (!window.confirm(`Apagar a resposta /${r.atalho}?`)) return;
    try {
      await api.apagarResposta(r.id);
      if (editando?.id === r.id) editar(null);
      carregar();
    } catch (e) {
      setErro(mensagemDe(e));
    }
  }

  return (
    <section className="respostas-rapidas">
      <h2>Respostas rápidas</h2>
      <p className="nota">
        Na conversa, digite <code>/</code> e o atalho para inserir o texto. Quem envia revisa antes;
        nada passa pela IA.
      </p>
      {lista === null ? (
        <p className="nota">Carregando…</p>
      ) : lista.length === 0 ? (
        <Vazio titulo="Nenhuma resposta rápida." texto="Crie a primeira abaixo." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Atalho</th>
              <th>Texto</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lista.map((r) => (
              <tr key={r.id}>
                <td>
                  <code>/{r.atalho}</code>
                </td>
                <td data-rotulo="Texto" className="texto-resposta">
                  {r.texto}
                </td>
                <td className="acoes">
                  <button type="button" onClick={() => editar(r)}>
                    Editar
                  </button>
                  <button type="button" className="perigo" onClick={() => apagar(r)}>
                    Apagar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="form-resposta" onSubmit={salvar}>
        <h3>{editando ? `Editar /${editando.atalho}` : "Nova resposta"}</h3>
        <label>
          Atalho
          <input
            value={atalho}
            onChange={(e) => setAtalho(e.target.value)}
            pattern="[a-z0-9][a-z0-9_\-]{0,39}"
            title="Letras minúsculas, números, - ou _; sem espaço"
            placeholder="ex.: documentos"
            required
            autoComplete="off"
          />
        </label>
        <label>
          Texto
          <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3} required />
        </label>
        {erro && (
          <p className="erro" role="alert">
            {erro}
          </p>
        )}
        <div className="acoes-form">
          {editando && (
            <button type="button" onClick={() => editar(null)}>
              Cancelar
            </button>
          )}
          <button type="submit">{editando ? "Salvar" : "Criar"}</button>
        </div>
      </form>
    </section>
  );
}
