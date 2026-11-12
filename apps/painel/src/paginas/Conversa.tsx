import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "react-router";
import {
  api,
  type CampoSensivel,
  type Detalhe,
  type Eu,
  type Ficha,
  midiaUrl,
  type Usuario,
} from "../api";
import { useAvisos } from "../tempoReal";
import { formatarHora, ROTULO_ATENDIMENTO } from "./Inbox";

const AUTOR = { cliente: "Cliente", ia: "IA", atendente: "Atendente", sistema: "Sistema" };
const CAMPOS: Record<CampoSensivel, string> = {
  telefone: "Telefone",
  cpf: "CPF",
  data_nascimento: "Nascimento",
};

export function Conversa({ eu }: { eu: Eu }) {
  const { id = "" } = useParams();
  const [conversa, setConversa] = useState<Detalhe | null>(null);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    api
      .conversa(id)
      .then(setConversa)
      .catch((e: Error) => setErro(e.message));
  }, [id]);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (aviso) => (aviso.conversa === id || aviso.tipo === "reconectado") && carregar(),
      [id, carregar],
    ),
  );

  async function agir(acao: () => Promise<unknown>) {
    setErro("");
    try {
      await acao();
      carregar();
    } catch (e) {
      setErro((e as Error).message);
    }
  }

  if (!conversa) return <p className="centro">{erro || "Carregando…"}</p>;
  const minha = conversa.atendimento === "assumida" && conversa.atendente_id === eu.id;

  return (
    <div className="conversa">
      <section className="historico">
        <header>
          <h2>{conversa.telefone ?? conversa.canal}</h2>
          <span className={`selo selo-${conversa.atendimento}`}>
            {ROTULO_ATENDIMENTO[conversa.atendimento]}
            {minha ? " (você)" : ""}
          </span>
          <Acoes conversa={conversa} eu={eu} minha={minha} agir={agir} />
        </header>
        {erro && (
          <p className="erro" role="alert">
            {erro}
          </p>
        )}
        <ol className="mensagens">
          {conversa.mensagens.map((m) => (
            <li key={m.id} className={`msg msg-${m.direcao}`}>
              <span className="autor">{AUTOR[m.autor]}</span>
              <p>{m.conteudo}</p>
              {m.anexos.map((anexo, indice) => (
                <a key={indice} href={midiaUrl(m.id, indice)} target="_blank" rel="noreferrer">
                  Anexo ({anexo.mime_type})
                </a>
              ))}
              <small>
                {formatarHora(m.criada_em)}
                {m.status_entrega ? ` · ${m.status_entrega}` : ""}
              </small>
            </li>
          ))}
        </ol>
        {(conversa.canal === "whatsapp" || conversa.canal === "evolution") &&
          (minha ? (
            <Envio conversa={conversa} agir={agir} />
          ) : (
            <button type="button" onClick={() => agir(() => api.assumir(id))}>
              Assumir e responder
            </button>
          ))}
      </section>
      <FichaCliente id={id} />
    </div>
  );
}

function Acoes({
  conversa,
  eu,
  minha,
  agir,
}: {
  conversa: Detalhe;
  eu: Eu;
  minha: boolean;
  agir: (acao: () => Promise<unknown>) => void;
}) {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [destino, setDestino] = useState("");
  const podeMexer = minha || eu.perfil === "gestor";

  useEffect(() => {
    if (podeMexer) api.usuarios().then(setUsuarios).catch(() => undefined);
  }, [podeMexer]);

  return (
    <div className="acoes">
      {!minha && (conversa.atendimento !== "assumida" || eu.perfil === "gestor") && (
        <button type="button" onClick={() => agir(() => api.assumir(conversa.id))}>
          Assumir
        </button>
      )}
      {conversa.atendimento !== "ia" && (conversa.atendimento === "handoff" || podeMexer) && (
        <button type="button" onClick={() => agir(() => api.devolver(conversa.id))}>
          Devolver para a IA
        </button>
      )}
      {conversa.atendimento === "assumida" && podeMexer && (
        <span className="transferir">
          <label>
            Transferir para
            <select value={destino} onChange={(e) => setDestino(e.target.value)}>
              <option value="">—</option>
              {usuarios
                .filter((u) => u.id !== conversa.atendente_id)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.email}
                  </option>
                ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!destino}
            onClick={() => agir(() => api.transferir(conversa.id, destino))}
          >
            Transferir
          </button>
        </span>
      )}
    </div>
  );
}

function Envio({
  conversa,
  agir,
}: {
  conversa: Detalhe;
  agir: (acao: () => Promise<unknown>) => void;
}) {
  const [texto, setTexto] = useState("");
  const [modelo, setModelo] = useState(conversa.modelos[0] ?? "");

  function enviarTexto(evento: FormEvent) {
    evento.preventDefault();
    if (!texto.trim()) return;
    agir(async () => {
      await api.enviar(conversa.id, { texto });
      setTexto("");
    });
  }

  return (
    <div className="envio">
      {/* Evolution não tem janela nem modelo: sempre texto (decisão 0009). */}
      {conversa.janela_aberta || conversa.canal === "evolution" ? (
        <form onSubmit={enviarTexto}>
          <label>
            Mensagem
            <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3} />
          </label>
          <button type="submit">Enviar</button>
        </form>
      ) : (
        <p className="aviso">Janela de 24 h fechada: só é possível enviar um modelo.</p>
      )}
      {conversa.modelos.length > 0 && (
        <div className="modelo">
          <label>
            Modelo
            <select value={modelo} onChange={(e) => setModelo(e.target.value)}>
              {conversa.modelos.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!modelo}
            onClick={() => agir(() => api.enviar(conversa.id, { modelo }))}
          >
            Enviar modelo
          </button>
        </div>
      )}
    </div>
  );
}

function FichaCliente({ id }: { id: string }) {
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [revelados, setRevelados] = useState<Partial<Record<CampoSensivel, string>>>({});

  useEffect(() => {
    setRevelados({});
    api.ficha(id).then(setFicha).catch(() => setFicha(null));
  }, [id]);

  async function revelar(campo: CampoSensivel) {
    const { valor } = await api.revelar(id, campo);
    setRevelados((atual) => ({ ...atual, [campo]: valor }));
  }

  if (!ficha) return <aside className="ficha" />;
  return (
    <aside className="ficha">
      <h3>Ficha</h3>
      <dl>
        {(Object.keys(CAMPOS) as CampoSensivel[])
          .filter((campo) => ficha.dados[campo])
          .map((campo) => (
            <div key={campo}>
              <dt>{CAMPOS[campo]}</dt>
              <dd>
                {revelados[campo] ?? ficha.dados[campo]}
                {!revelados[campo] && (
                  <button type="button" className="link" onClick={() => revelar(campo)}>
                    Revelar
                  </button>
                )}
              </dd>
            </div>
          ))}
        {ficha.uf && (
          <div>
            <dt>UF</dt>
            <dd>{ficha.uf}</dd>
          </div>
        )}
        {ficha.publico && (
          <div>
            <dt>Público</dt>
            <dd>{ficha.publico}</dd>
          </div>
        )}
        {ficha.handoff_reason && (
          <div>
            <dt>Motivo do handoff</dt>
            <dd>{ficha.handoff_reason}</dd>
          </div>
        )}
      </dl>
      <p className="nota">Revelar um dado fica registrado na auditoria.</p>
    </aside>
  );
}
