import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Link, useParams } from "react-router";
import {
  api,
  type CampoSensivel,
  type Detalhe,
  type Eu,
  exportarUrl,
  type Ficha,
  midiaUrl,
  type Trilha,
  type Usuario,
} from "../api";
import { confirmarTomada, textoDoAviso, useAvisoDesfazer } from "../componentes/Desfazer";
import { Vazio } from "../componentes/Vazio";
import {
  ATENCAO,
  CHAMADAS,
  PUBLICOS,
  dolar,
  ETAPAS,
  MODELOS,
  MOTIVOS_HANDOFF,
  NOS,
  rotulo,
  tokens,
} from "../rotulos";
import { useAvisos } from "../tempoReal";
import { formatarHora, ROTULO_ATENDIMENTO, textoDaEspera } from "./Inbox";

const AUTOR = { cliente: "Cliente", ia: "IA", atendente: "Equipe", sistema: "Sistema" };
const CAMPOS: Record<CampoSensivel, string> = {
  telefone: "Telefone",
  cpf: "CPF",
  data_nascimento: "Nascimento",
  email: "E-mail",
};

const STATUS_ENTREGA: Record<string, string> = {
  sent: "enviada",
  delivered: "entregue",
  read: "lida",
  failed: "falhou",
};

type Aba = "mensagens" | "ficha" | "ia";

// `fichaEmAba`: sem espaço para a coluna lateral (conversa ao lado da lista),
// ficha e trilha da IA viram abas ao lado das mensagens.
export function Conversa({ eu, fichaEmAba = false }: { eu: Eu; fichaEmAba?: boolean }) {
  const { id = "" } = useParams();
  const [aba, setAba] = useState<Aba>("mensagens");
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

  // A leitura começa pela última mensagem e a acompanha enquanto a pessoa está
  // no fim. `fim` vem depois do envio: rolar até a última mensagem a deixaria
  // atrás do envio fixo.
  const fim = useRef<HTMLDivElement | null>(null);
  const noFim = useRef(true);
  useEffect(() => {
    const medir = () => {
      const caixa = fim.current?.getBoundingClientRect();
      if (caixa) noFim.current = caixa.bottom <= window.innerHeight + 80;
    };
    window.addEventListener("scroll", medir, { passive: true });
    return () => window.removeEventListener("scroll", medir);
  }, []);
  const ultima = conversa?.mensagens[conversa.mensagens.length - 1]?.id;
  useEffect(() => {
    if (ultima !== undefined && noFim.current) fim.current?.scrollIntoView({ block: "end" });
    // Assumir troca o botão pelo envio, mais alto: o fim muda de lugar.
  }, [ultima, conversa?.atendimento]);

  // Quem está com a conversa: para o selo, a transferência e a confirmação de tomada.
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  useEffect(() => {
    api
      .usuarios()
      .then(setUsuarios)
      .catch(() => undefined);
  }, []);
  const avisar = useAvisoDesfazer();
  // "Assumir e responder" leva o cursor para a mensagem.
  const [focarEnvio, setFocarEnvio] = useState(false);

  if (!conversa) return <p className="centro">{erro || "Carregando…"}</p>;
  const minha = conversa.atendimento === "assumida" && conversa.atendente_id === eu.id;
  const dono = usuarios.find((u) => u.id === conversa.atendente_id)?.nome ?? "outra pessoa";

  // Assumir e devolver valem na hora; o aviso deixa desfazer por 5 s.
  function mudar(acao: "assumir" | "devolver") {
    if (acao === "assumir" && conversa?.atendimento === "assumida" && !confirmarTomada(dono)) return;
    void agir(async () => {
      await (acao === "assumir" ? api.assumir(id) : api.devolver(id));
      avisar({
        id,
        texto: textoDoAviso(acao, conversa?.telefone ?? conversa?.canal ?? ""),
        depois: carregar,
      });
    });
  }

  return (
    <div className={fichaEmAba ? "conversa em-abas" : "conversa"}>
      <section className="historico">
        <header>
          <Link className="voltar" to="/">
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} strokeWidth={2} />
            Conversas
          </Link>
          <div className="identidade">
            <h1>{conversa.telefone ?? conversa.canal}</h1>
            <p>
              <span className={`selo selo-${conversa.atendimento}`}>
                {ROTULO_ATENDIMENTO[conversa.atendimento]}
                {conversa.atendente_id && (minha ? " (você)" : ` · ${dono}`)}
              </span>
              <span>{conversa.canal === "evolution" ? "Evolution" : "WhatsApp oficial"}</span>
              {conversa.etapa && <span>{rotulo(ETAPAS, conversa.etapa)}</span>}
              {conversa.canal === "whatsapp" && (
                <span className={conversa.janela_aberta ? "janela aberta" : "janela fechada"}>
                  {conversa.janela_aberta ? "janela aberta" : "janela fechada"}
                </span>
              )}
              {conversa.aguardando_desde && (
                <span className="espera">{textoDaEspera(conversa, Date.now())}</span>
              )}
            </p>
          </div>
          <Acoes
            conversa={conversa}
            eu={eu}
            minha={minha}
            usuarios={usuarios}
            agir={agir}
            mudar={mudar}
          />
          {erro && (
            <p className="erro" role="alert">
              {erro}
            </p>
          )}
        </header>
        {(conversa.atencao ?? []).length > 0 && (
          <p className="faixa-atencao">
            <strong>{(conversa.atencao ?? []).map((a) => rotulo(ATENCAO, a)).join(" · ")}</strong>
            {conversa.motivo_handoff && ` — ${rotulo(MOTIVOS_HANDOFF, conversa.motivo_handoff)}`}
          </p>
        )}
        {fichaEmAba && (
          <Abas
            rotulo="Conversa"
            opcoes={[
              ["mensagens", "Mensagens"],
              ["ficha", "Ficha"],
              ["ia", "IA"],
            ]}
            valor={aba}
            mudar={setAba}
          />
        )}
        {fichaEmAba && aba === "ficha" && <FichaCliente id={id} />}
        {fichaEmAba && aba === "ia" && <TrilhaIa id={id} />}
        {(!fichaEmAba || aba === "mensagens") && (
          <>
            <ol className="mensagens">
              {conversa.mensagens.map((m) => (
                <li key={m.id} className={`msg msg-${m.direcao} msg-${m.autor}`}>
                  <span className="autor">{AUTOR[m.autor]}</span>
                  <p>{m.conteudo}</p>
                  {m.anexos.map((anexo, indice) => (
                    <a key={indice} href={midiaUrl(m.id, indice)} target="_blank" rel="noreferrer">
                      Anexo ({anexo.mime_type})
                    </a>
                  ))}
                  <small>
                    {formatarHora(m.criada_em)}
                    {m.status_entrega && (
                      <span className={m.status_entrega === "failed" ? "status falhou" : "status"}>
                        {" · "}
                        {STATUS_ENTREGA[m.status_entrega] ?? m.status_entrega}
                      </span>
                    )}
                  </small>
                </li>
              ))}
            </ol>
            {(conversa.canal === "whatsapp" || conversa.canal === "evolution") &&
              (minha ? (
                <Envio
                  conversa={conversa}
                  focar={focarEnvio}
                  agir={(acao) => {
                    // Quem envia quer ver a própria mensagem, mesmo lendo mais acima.
                    noFim.current = true;
                    return agir(acao);
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="principal"
                  onClick={() => {
                    setFocarEnvio(true);
                    mudar("assumir");
                  }}
                >
                  Assumir e responder
                </button>
              ))}
            <div ref={fim} />
          </>
        )}
      </section>
      {!fichaEmAba && <Lateral id={id} />}
    </div>
  );
}

function Acoes({
  conversa,
  eu,
  minha,
  usuarios,
  agir,
  mudar,
}: {
  conversa: Detalhe;
  eu: Eu;
  minha: boolean;
  usuarios: Usuario[];
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mudar: (acao: "assumir" | "devolver") => void;
}) {
  const [destino, setDestino] = useState("");
  const podeMexer = minha || eu.perfil === "gestor";

  return (
    <div className="acoes">
      {!minha && (conversa.atendimento !== "assumida" || eu.perfil === "gestor") && (
        <button type="button" onClick={() => mudar("assumir")}>
          Assumir
        </button>
      )}
      {conversa.atendimento !== "ia" && (conversa.atendimento === "handoff" || podeMexer) && (
        <button type="button" onClick={() => mudar("devolver")}>
          Devolver para a IA
        </button>
      )}
      {/* O que não é do momento fica recolhido: o cabeçalho mostra só quem responde. */}
      <details
        className="mais"
        onKeyDown={(e) => {
          if (e.key === "Escape") e.currentTarget.open = false;
        }}
      >
        <summary>Mais</summary>
        <div className="mais-painel">
          {conversa.atendimento === "assumida" && podeMexer && (
            <span className="transferir">
              <label>
                Transferir para
                <select value={destino} onChange={(e) => setDestino(e.target.value)}>
                  <option value="">Escolha a pessoa</option>
                  {usuarios
                    .filter((u) => u.id !== conversa.atendente_id)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.nome}
                      </option>
                    ))}
                </select>
              </label>
              <button
                type="button"
                disabled={!destino}
                onClick={() => agir(() => api.transferir(conversa.id, destino)).then(() => setDestino(""))}
              >
                Transferir
              </button>
            </span>
          )}
          <a className="botao" href={exportarUrl(conversa.id)}>
            Exportar conversa (.md)
          </a>
        </div>
      </details>
    </div>
  );
}

function Envio({
  conversa,
  focar,
  agir,
}: {
  conversa: Detalhe;
  focar: boolean;
  agir: (acao: () => Promise<unknown>) => Promise<void>;
}) {
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [modelo, setModelo] = useState(conversa.modelos[0] ?? "");

  async function enviarTexto(evento: FormEvent) {
    evento.preventDefault();
    if (!texto.trim() || enviando) return;
    setEnviando(true);
    await agir(async () => {
      await api.enviar(conversa.id, { texto });
      setTexto("");
    });
    setEnviando(false);
  }

  function enviarModelo() {
    // O texto do modelo fica cadastrado na Meta: o painel não tem como mostrá-lo.
    const pergunta =
      `Enviar o modelo "${rotulo(MODELOS, modelo)}" para ${conversa.telefone}? ` +
      "O cliente recebe o texto aprovado na Meta, que o painel não mostra.";
    if (window.confirm(pergunta)) void agir(() => api.enviar(conversa.id, { modelo }));
  }

  const janelaAberta = conversa.janela_aberta || conversa.canal === "evolution";
  const blocoModelo = conversa.modelos.length > 0 && (
    <div className="modelo">
      <label>
        Modelo
        <select value={modelo} onChange={(e) => setModelo(e.target.value)}>
          {conversa.modelos.map((m) => (
            <option key={m} value={m}>
              {rotulo(MODELOS, m)}
            </option>
          ))}
        </select>
      </label>
      <button type="button" disabled={!modelo} onClick={enviarModelo}>
        Enviar modelo
      </button>
    </div>
  );

  return (
    <div className="envio">
      {/* Evolution não tem janela nem modelo: sempre texto (decisão 0009). */}
      {janelaAberta ? (
        <form onSubmit={enviarTexto}>
          <label>
            Mensagem
            <textarea
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              rows={3}
              autoFocus={focar}
            />
          </label>
          <button type="submit" disabled={enviando}>
            {enviando ? "Enviando…" : "Enviar"}
          </button>
        </form>
      ) : (
        <p className="aviso">Janela de 24 h fechada: só é possível enviar um modelo.</p>
      )}
      {/* Com a janela aberta o texto livre resolve; o modelo fica a um clique. */}
      {blocoModelo && janelaAberta ? (
        <details>
          <summary>Enviar um modelo</summary>
          {blocoModelo}
        </details>
      ) : (
        blocoModelo
      )}
    </div>
  );
}

// Coluna da direita: a Ficha do cliente ou a trilha da IA, turno a turno.
function Lateral({ id }: { id: string }) {
  const [aba, setAba] = useState<"ficha" | "ia">("ficha");
  return (
    <aside className="lateral">
      <Abas
        rotulo="Painel lateral"
        opcoes={[
          ["ficha", "Ficha"],
          ["ia", "IA"],
        ]}
        valor={aba}
        mudar={setAba}
      />
      {aba === "ficha" ? <FichaCliente id={id} /> : <TrilhaIa id={id} />}
    </aside>
  );
}

function Abas<T extends string>({
  rotulo,
  opcoes,
  valor,
  mudar,
}: {
  rotulo: string;
  opcoes: [T, string][];
  valor: T;
  mudar: (v: T) => void;
}) {
  return (
    <div role="tablist" aria-label={rotulo} className="abas-laterais">
      {opcoes.map(([v, texto]) => (
        <button
          key={v}
          type="button"
          role="tab"
          aria-selected={valor === v}
          className={valor === v ? "ativo" : ""}
          onClick={() => mudar(v)}
        >
          {texto}
        </button>
      ))}
    </div>
  );
}

function TrilhaIa({ id }: { id: string }) {
  const [trilha, setTrilha] = useState<Trilha | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(() => {
    api
      .turnos(id)
      .then((t) => {
        setTrilha(t);
        setErro("");
      })
      .catch((e: unknown) => setErro(e instanceof Error ? e.message : "falha ao carregar"));
  }, [id]);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (aviso) => (aviso.conversa === id || aviso.tipo === "reconectado") && carregar(),
      [id, carregar],
    ),
  );

  if (erro)
    return (
      <p className="erro" role="alert">
        {erro}
      </p>
    );
  if (!trilha) return <p className="centro">Carregando…</p>;
  if (trilha.turnos.length === 0)
    return (
      <Vazio
        titulo="Nenhum turno ainda."
        texto="Cada resposta da IA aparece aqui, com o que ela fez."
      />
    );

  return (
    <div className="trilha">
      {trilha.custo_usd !== null && (
        <p className="trilha-total">
          {dolar(trilha.custo_usd)} · {tokens(trilha.tokens ?? 0)} tokens nesta conversa
        </p>
      )}
      <ol>
        {trilha.turnos.map((t) => (
          <li key={t.id} className="turno">
            <div className="turno-topo">
              <time dateTime={t.criado_em}>{formatarHora(t.criado_em)}</time>
              {t.etapa && <span className="etapa">{rotulo(ETAPAS, t.etapa)}</span>}
              {t.custo_usd !== null && <span className="turno-custo">{dolar(t.custo_usd)}</span>}
            </div>
            <p className="turno-caminho">{t.caminho.map((n) => rotulo(NOS, n)).join(" → ")}</p>
            {t.classificacao && (
              <p className="turno-classificacao">
                Intenção: {t.classificacao.intencao ?? "—"} · público:{" "}
                {t.classificacao.publico ?? "—"}
                {t.classificacao.confianca !== null &&
                  ` · confiança ${Math.round(t.classificacao.confianca * 100)}%`}
              </p>
            )}
            {t.motivo && <p className="motivo">Motivo: {rotulo(MOTIVOS_HANDOFF, t.motivo)}</p>}
            {t.chamadas.length > 0 && (
              <ul className="turno-chamadas">
                {t.chamadas.map((c, i) => (
                  <li
                    key={i}
                    className={
                      c.status && c.status !== "ok" && !c.status.startsWith("2") ? "falhou" : ""
                    }
                  >
                    <span>{rotulo(CHAMADAS, c.nome)}</span>
                    <span>{c.status ?? "—"}</span>
                    <span>{Math.round(c.latencia_ms)} ms</span>
                    {c.custo_usd !== null && <span>{dolar(c.custo_usd)}</span>}
                    {c.tokens_entrada !== null && (
                      <span>
                        {tokens(c.tokens_entrada)}+{tokens(c.tokens_saida ?? 0)} tok
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function FichaCliente({ id }: { id: string }) {
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [revelados, setRevelados] = useState<Partial<Record<CampoSensivel, string>>>({});

  useEffect(() => {
    setRevelados({});
    api
      .ficha(id)
      .then(setFicha)
      .catch(() => setFicha(null));
  }, [id]);

  const [erroRevelar, setErroRevelar] = useState("");
  async function revelar(campo: CampoSensivel) {
    setErroRevelar("");
    try {
      const { valor } = await api.revelar(id, campo);
      setRevelados((atual) => ({ ...atual, [campo]: valor }));
    } catch (e) {
      setErroRevelar(
        e instanceof Error ? `Não deu para revelar: ${e.message}` : "Não deu para revelar.",
      );
    }
  }

  if (!ficha) return <div className="ficha" />;
  return (
    <div className="ficha">
      <h2>Ficha</h2>
      <dl>
        {ficha.nome && (
          <div>
            <dt>Nome</dt>
            <dd>{ficha.nome}</dd>
          </div>
        )}
        {(Object.keys(CAMPOS) as CampoSensivel[])
          .filter((campo) => ficha.dados[campo])
          .map((campo) => (
            <div key={campo}>
              <dt>{CAMPOS[campo]}</dt>
              <dd>
                {revelados[campo] ?? ficha.dados[campo]}
                {!revelados[campo] && (
                  <button
                    type="button"
                    className="link"
                    aria-describedby="aviso-auditoria"
                    onClick={() => revelar(campo)}
                  >
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
            <dd>{rotulo(PUBLICOS, ficha.publico)}</dd>
          </div>
        )}
        {ficha.handoff_reason && (
          <div>
            <dt>Motivo do handoff</dt>
            <dd>{rotulo(MOTIVOS_HANDOFF, ficha.handoff_reason)}</dd>
          </div>
        )}
      </dl>
      {erroRevelar && (
        <p className="erro" role="alert">
          {erroRevelar}
        </p>
      )}
      <p className="nota" id="aviso-auditoria">
        Revelar um dado fica registrado na auditoria, em seu nome.
      </p>
    </div>
  );
}
