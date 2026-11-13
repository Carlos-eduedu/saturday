import { useCallback, useEffect, useRef, useState } from "react";
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
import { Compositor } from "../componentes/Compositor";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import {
  ATENCAO,
  CHAMADAS,
  PUBLICOS,
  dolar,
  ETAPAS,
  MOTIVOS_HANDOFF,
  NOS,
  reais,
  rotulo,
  STATUS_PROPOSTA,
  TIPOS_DE_PROVA,
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

// Conteúdo que `painel/acoes.enviar_anexo` grava quando o anexo vai sem legenda.
const ANEXO_SEM_LEGENDA = /^\[(imagem|documento|áudio) .+\]$/;

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
    // Assumir libera o campo de escrever: o fim pode mudar de lugar.
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
  // Assumir pelo cabeçalho leva o cursor para a mensagem.
  const [focarEnvio, setFocarEnvio] = useState(false);
  // Assumir, devolver e transferir em andamento: o duplo clique não repete.
  const [ocupado, setOcupado] = useState(false);
  function agirUmaVez(acao: () => Promise<unknown>): Promise<void> {
    if (ocupado) return Promise.resolve();
    setOcupado(true);
    return agir(acao).finally(() => setOcupado(false));
  }

  if (!conversa)
    return erro ? (
      <Falha titulo="Não deu para abrir a conversa." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );
  const minha = conversa.atendimento === "assumida" && conversa.atendente_id === eu.id;
  const dono = usuarios.find((u) => u.id === conversa.atendente_id)?.nome ?? "outra pessoa";

  // Assumir e devolver valem na hora; o aviso deixa desfazer por 5 s.
  function mudar(acao: "assumir" | "devolver") {
    if (acao === "assumir" && conversa?.atendimento === "assumida" && !confirmarTomada(dono)) return;
    setFocarEnvio(acao === "assumir");
    void agirUmaVez(async () => {
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
            <span className="voltar-texto">Conversas</span>
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
            agir={agirUmaVez}
            ocupado={ocupado}
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
                  {/* Anexo sem legenda grava "[documento nome]": o anexo já se mostra. */}
                  {!(m.anexos.length > 0 && ANEXO_SEM_LEGENDA.test(m.conteudo)) && <p>{m.conteudo}</p>}
                  {m.anexos.map((anexo, indice) => {
                    const url = midiaUrl(m.id, indice);
                    if (anexo.mime_type.startsWith("audio/"))
                      return <audio key={indice} className="anexo-audio" controls preload="none" src={url} />;
                    if (anexo.mime_type.startsWith("image/"))
                      return (
                        <a key={indice} className="anexo-imagem" href={url} target="_blank" rel="noreferrer">
                          <img src={url} alt={anexo.nome ?? "Imagem enviada"} loading="lazy" />
                        </a>
                      );
                    return (
                      <a key={indice} className="anexo-arquivo" href={url} target="_blank" rel="noreferrer">
                        {anexo.nome ?? `Anexo (${anexo.mime_type})`}
                      </a>
                    );
                  })}
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
            {(conversa.canal === "whatsapp" || conversa.canal === "evolution") && (
              <Compositor
                conversa={conversa}
                eu={eu}
                minha={minha}
                focar={focarEnvio}
                assumir={
                  !minha && (conversa.atendimento !== "assumida" || eu.perfil === "gestor")
                    ? {
                        acao: () => {
                          setFocarEnvio(true);
                          mudar("assumir");
                        },
                        ocupado,
                      }
                    : undefined
                }
                agir={(acao) => {
                  // Quem envia quer ver a própria mensagem, mesmo lendo mais acima.
                  noFim.current = true;
                  return agir(acao);
                }}
              />
            )}
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
  ocupado,
}: {
  conversa: Detalhe;
  eu: Eu;
  minha: boolean;
  usuarios: Usuario[];
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mudar: (acao: "assumir" | "devolver") => void;
  ocupado: boolean;
}) {
  const [destino, setDestino] = useState("");
  const podeMexer = minha || eu.perfil === "gestor";

  return (
    <div className="acoes">
      {!minha && (conversa.atendimento !== "assumida" || eu.perfil === "gestor") && (
        <button type="button" disabled={ocupado} onClick={() => mudar("assumir")}>
          Assumir
        </button>
      )}
      {conversa.atendimento !== "ia" && (conversa.atendimento === "handoff" || podeMexer) && (
        <button type="button" disabled={ocupado} onClick={() => mudar("devolver")}>
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
                disabled={!destino || ocupado}
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

  // Falhar ao recarregar mantém a última trilha à vista.
  if (!trilha)
    return erro ? (
      <Falha titulo="Não deu para carregar a trilha da IA." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );
  if (trilha.turnos.length === 0)
    return (
      <Vazio
        titulo="Nenhum turno ainda."
        texto="Cada resposta da IA aparece aqui, com o que ela fez."
      />
    );

  return (
    <div className="trilha">
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
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

  // Falhar ao recarregar mantém a última ficha: some só o que nunca chegou.
  const [erroCarga, setErroCarga] = useState("");
  const carregar = useCallback(() => {
    api
      .ficha(id)
      .then((f) => {
        setFicha(f);
        setErroCarga("");
      })
      .catch((e: unknown) =>
        setErroCarga(e instanceof Error ? e.message : "Não deu para carregar a ficha."),
      );
  }, [id]);
  useEffect(() => {
    setRevelados({});
    carregar();
  }, [id, carregar]);
  // A oferta e a proposta mudam durante a conversa: a ficha acompanha.
  useAvisos(useCallback((aviso) => aviso.conversa === id && carregar(), [id, carregar]));

  const [erroRevelar, setErroRevelar] = useState("");
  // Cada clique em Revelar grava auditoria: um pedido por vez.
  const [revelando, setRevelando] = useState<CampoSensivel | null>(null);
  async function revelar(campo: CampoSensivel) {
    if (revelando) return;
    setRevelando(campo);
    setErroRevelar("");
    try {
      const { valor } = await api.revelar(id, campo);
      setRevelados((atual) => ({ ...atual, [campo]: valor }));
    } catch (e) {
      setErroRevelar(
        e instanceof Error ? `Não deu para revelar: ${e.message}` : "Não deu para revelar.",
      );
    }
    setRevelando(null);
  }

  if (!ficha)
    return erroCarga ? (
      <Falha titulo="Não deu para carregar a ficha." texto={erroCarga} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );
  return (
    <>
      <Acompanhamento ficha={ficha} />
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
                      disabled={revelando !== null}
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
    </>
  );
}

const porcento = (valor: string) =>
  `${Number(valor).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}% a.m.`;

// O que a IA disse em valores, ao lado da fala: oferta vigente, proposta no
// banco e as provas do SIM. Só aparece quando a jornada chegou a algum deles.
function Acompanhamento({ ficha }: { ficha: Ficha }) {
  const { oferta, proposta, consentimentos } = ficha;
  if (!oferta && !proposta && consentimentos.length === 0) return null;
  return (
    <div className="ficha">
      {oferta && (
        <>
          <h2>Oferta vigente</h2>
          <dl>
            <div>
              <dt>Liberado</dt>
              <dd>
                {reais(oferta.liberado)}
                {oferta.limitado_ao_teto && <span className="nota"> (limitado ao teto)</span>}
              </dd>
            </div>
            <div>
              <dt>Parcelas</dt>
              <dd>
                {oferta.numero_parcelas} × {reais(oferta.valor_parcela)}
              </dd>
            </div>
            <div>
              <dt>Taxa e CET</dt>
              <dd>
                {porcento(oferta.taxa_mensal)} · CET {porcento(oferta.cet_mensal)}
              </dd>
            </div>
            <div>
              <dt>Seguro</dt>
              <dd>{oferta.seguro_aplicado ? reais(oferta.valor_seguro) : "Sem seguro"}</dd>
            </div>
          </dl>
        </>
      )}
      {proposta && (
        <>
          <h2>Proposta no banco</h2>
          <dl>
            <div>
              <dt>Status</dt>
              <dd className="texto">
                {proposta.status ? rotulo(STATUS_PROPOSTA, proposta.status) : "Ainda sem status"}
              </dd>
            </div>
            <div>
              <dt>Parcelas</dt>
              <dd>
                {proposta.numero_parcelas} × {reais(proposta.valor_parcela)}
              </dd>
            </div>
          </dl>
          {proposta.difere_da_oferta && (
            <p className="faixa-atencao">
              <strong>Difere da oferta vigente.</strong> Confira qual valor a IA passou ao cliente.
            </p>
          )}
          <p className="nota">
            <Link to="/granatech">Ver na Granatech</Link>
          </p>
        </>
      )}
      <h2>Consentimento</h2>
      {consentimentos.length === 0 ? (
        <p className="nota">Nenhuma prova de consentimento gravada.</p>
      ) : (
        <ul className="provas">
          {consentimentos.map((prova) => (
            <li key={`${prova.tipo}-${prova.criada_em}`}>
              <strong>{rotulo(TIPOS_DE_PROVA, prova.tipo)}</strong>
              <span>
                respondeu “{prova.resposta_literal}” · {formatarHora(prova.criada_em)}
              </span>
              <details>
                <summary>Texto mostrado ({prova.versao})</summary>
                <p>{prova.texto_mostrado}</p>
              </details>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
