import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Vazio } from "../componentes/Vazio";
import {
  api,
  type Canais as DadosCanais,
  type DetalhesInstancia,
  ErroApi,
  type InstanciaEvolution,
  type Qr,
} from "../api";

// Tela Canais (decisão 0010), só para gestor: números da Meta para consulta e
// instâncias da Evolution geridas aqui. O QR se renova sozinho até conectar.
// Detalhes mostram o webhook e as configurações gravados na Evolution, lado a
// lado com o que o Saturday aplica; o token nunca chega ao navegador.

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

  if (!canais) return <p className="centro">{erro || "Carregando…"}</p>;

  return (
    <div className="canais">
      <h1 className="titulo-tela">Canais</h1>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}

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
              mostrarQr={(nome, qr) => setQrDe({ nome, qr })}
              detalhar={setDetalhesDe}
            />
            <NovaInstancia agir={agir} mostrarQr={(nome, qr) => setQrDe({ nome, qr })} />
          </>
        )}
      </section>

      {detalhesDe && (
        <PainelDetalhes key={detalhesDe} nome={detalhesDe} fechar={() => setDetalhesDe(null)} />
      )}

      {qrDe && (
        <PainelQr
          nome={qrDe.nome}
          inicial={qrDe.qr}
          fechar={() => {
            setQrDe(null);
            carregar();
          }}
        />
      )}
    </div>
  );
}

function TabelaInstancias({
  instancias,
  agir,
  mostrarQr,
  detalhar,
}: {
  instancias: InstanciaEvolution[];
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mostrarQr: (nome: string, qr: Qr) => void;
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
          <tr key={i.nome}>
            <td>{i.nome}</td>
            <td data-rotulo="Estado">
              <span className={`estado-instancia estado-${i.estado}`}>
                {ROTULO_ESTADO[i.estado] ?? i.estado}
              </span>
            </td>
            <td data-rotulo="Telefone">{i.telefone}</td>
            <td data-rotulo="Conversas (7 dias)">{i.conversas_7_dias}</td>
            <td className="acoes">
              <button type="button" onClick={() => detalhar(i.nome)}>
                Detalhes
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

  return (
    <section className="qr" aria-live="polite">
      <h2>Conectar {nome}</h2>
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
      <button type="button" onClick={fechar}>
        Fechar
      </button>
    </section>
  );
}

function PainelDetalhes({ nome, fechar }: { nome: string; fechar: () => void }) {
  const [detalhes, setDetalhes] = useState<DetalhesInstancia | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    api
      .detalhesInstancia(nome)
      .then(setDetalhes)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, [nome]);

  return (
    <section className="detalhes-instancia" aria-live="polite">
      <h2>Detalhes de {nome}</h2>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {!detalhes && !erro && <p className="nota">Consultando a Evolution…</p>}
      {detalhes && <ConteudoDetalhes detalhes={detalhes} />}
      <button type="button" onClick={fechar}>
        Fechar
      </button>
    </section>
  );
}

function ConteudoDetalhes({ detalhes }: { detalhes: DetalhesInstancia }) {
  const { webhook, configuracoes, divergencias } = detalhes;
  // Esperados primeiro, depois o que a instância manda a mais.
  const eventos = [
    ...webhook.eventos_esperados,
    ...webhook.eventos.filter((e) => !webhook.eventos_esperados.includes(e)),
  ];

  return (
    <>
      {divergencias.length === 0 ? (
        <p className="confere">Tudo confere com o que o Saturday aplica.</p>
      ) : (
        <div className="divergencias" role="status">
          <p>
            {divergencias.length} diferença(s) em relação ao que o Saturday aplica:
          </p>
          <ul>
            {divergencias.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
          <p className="nota">
            Para reaplicar a configuração: desconecte a instância e clique em Reconectar.
          </p>
        </div>
      )}

      <h3>Webhook</h3>
      {!webhook.configurado ? (
        <p className="vazio">A instância não tem webhook.</p>
      ) : (
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

      <h3>Eventos</h3>
      <ul className="eventos">
        {eventos.map((e) => {
          const esperado = webhook.eventos_esperados.includes(e);
          const ligado = webhook.eventos.includes(e);
          const situacao = !ligado ? "falta" : esperado ? "usado" : "ignorado";
          const texto = {
            falta: "falta",
            usado: "usado pelo Saturday",
            ignorado: "chega, mas o Saturday ignora",
          }[situacao];
          return (
            <li key={e} className={`evento evento-${situacao}`}>
              <code>{e}</code> <span>{texto}</span>
            </li>
          );
        })}
      </ul>

      <h3>Configurações da instância</h3>
      {configuracoes.length === 0 ? (
        <p className="vazio">A Evolution não devolveu configurações.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Configuração</th>
              <th>Atual</th>
              <th>Esperado</th>
            </tr>
          </thead>
          <tbody>
            {configuracoes.map((c) => (
              <tr key={c.nome} className={c.atual === c.esperado ? undefined : "diverge"}>
                <td>
                  {ROTULO_CONFIGURACAO[c.nome] ?? c.nome} <small>{c.nome}</small>
                </td>
                <td data-rotulo="Atual">{simNao(c.atual)}</td>
                <td data-rotulo="Esperado">{simNao(c.esperado)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
