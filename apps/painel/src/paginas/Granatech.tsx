import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Cancel01Icon, CancelCircleIcon, CheckmarkCircle02Icon, Download04Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Link } from "react-router";
import LatticeLoader, { type StatusLattice } from "../componentes/LatticeLoader";
import { CamposConta, CONTA_VAZIA } from "../componentes/CamposConta";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import {
  type Acoes,
  api,
  type ConsultaGranatech,
  type ConsultaGranatechDetalhe,
  type ContaNova,
  ErroApi,
  type Eu,
  type EventoGranatech,
  type FiltroGranatech,
  type Homologacao as DadosHomologacao,
  type PropostaGranatech,
  type PropostaGranatechDetalhe,
  type Rodada,
  type RodadaDetalhe,
  rodadaZipUrl,
  type SituacaoRodada,
} from "../api";
import { ETAPAS, rotulo, reais } from "../rotulos";
import { type Aviso, useAvisos } from "../tempoReal";

// Aba Granatech (decisão 0013). Todos veem consultas e propostas; só o gestor
// age. Abrir consulta, simular e criar proposta não existem aqui: dependem do
// SIM do cliente, que só vem pela conversa. Quem decide se uma ação cabe é a
// API (`acoes`: null = pode, texto = motivo); a tela só mostra.

type Aba = "consultas" | "propostas";
type Selecao = { aba: Aba; id: number } | null;
type Agir = (acao: () => Promise<unknown>, feito: string | ((r: unknown) => string)) => void;

function mensagemDe(erro: unknown): string {
  return erro instanceof ErroApi ? erro.message : "falha inesperada";
}

const dataHora = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : "—";

export function Granatech({ eu }: { eu: Eu }) {
  const gestor = eu.perfil === "gestor";
  const [aba, setAba] = useState<Aba>("propostas");
  const [filtro, setFiltro] = useState<FiltroGranatech>({});
  const [consultas, setConsultas] = useState<ConsultaGranatech[] | null>(null);
  const [propostas, setPropostas] = useState<PropostaGranatech[] | null>(null);
  const [selecao, setSelecao] = useState<Selecao>(null);
  const [versao, setVersao] = useState(0);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");

  const carregar = useCallback(() => {
    setErro("");
    const pedido = aba === "consultas" ? api.consultasGranatech(filtro) : api.propostasGranatech(filtro);
    pedido
      .then((linhas) =>
        aba === "consultas"
          ? setConsultas(linhas as ConsultaGranatech[])
          : setPropostas(linhas as PropostaGranatech[]),
      )
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, [aba, filtro]);
  useEffect(carregar, [carregar]);

  useAvisos(
    useCallback(
      (a: Aviso) => {
        if (a.tipo !== "granatech" && a.tipo !== "reconectado") return;
        carregar();
        setVersao((v) => v + 1);
      },
      [carregar],
    ),
  );

  // Uma ação por vez: reenviar o link duas vezes manda duas mensagens ao cliente.
  const emAndamento = useRef(false);
  const agir: Agir = (acao, feito) => {
    if (emAndamento.current) return;
    emAndamento.current = true;
    setErro("");
    setAviso("Aguarde…");
    acao()
      .then((r) => setAviso(typeof feito === "string" ? feito : feito(r)))
      .catch((e: unknown) => {
        setAviso("");
        setErro(mensagemDe(e));
      })
      .finally(() => {
        emAndamento.current = false;
        carregar();
        setVersao((v) => v + 1);
      });
  };

  return (
    <div className="canais granatech">
      <h1 className="titulo-tela">Granatech</h1>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="confere">{aviso}</p>}

      <section>
        <div className="filtros">
          <div role="tablist" aria-label="Listas da Granatech">
            {(["propostas", "consultas"] as const).map((a) => (
              <button
                key={a}
                type="button"
                role="tab"
                aria-selected={aba === a}
                className={aba === a ? "ativo" : undefined}
                onClick={() => {
                  setAba(a);
                  setSelecao(null);
                }}
              >
                {a === "propostas" ? "Propostas" : "Consultas"}
              </button>
            ))}
          </div>
          <Filtros aoFiltrar={setFiltro} />
        </div>
        {aba === "consultas" ? (
          <ListaConsultas linhas={consultas} selecionar={(id) => setSelecao({ aba, id })} />
        ) : (
          <ListaPropostas linhas={propostas} selecionar={(id) => setSelecao({ aba, id })} />
        )}
      </section>

      {selecao?.aba === "consultas" && (
        <DetalheConsulta
          key={`c${selecao.id}`}
          id={selecao.id}
          versao={versao}
          gestor={gestor}
          agir={agir}
          abrirProposta={(id) => {
            setAba("propostas");
            setSelecao({ aba: "propostas", id });
          }}
        />
      )}
      {selecao?.aba === "propostas" && (
        <DetalheProposta
          key={`p${selecao.id}`}
          id={selecao.id}
          versao={versao}
          gestor={gestor}
          agir={agir}
          abrirConsulta={(id) => {
            setAba("consultas");
            setSelecao({ aba: "consultas", id });
          }}
        />
      )}

      {gestor && <Homologacao />}
    </div>
  );
}

// Homologação Granatech (decisão 0014): só o gestor, e só fora de produção (a
// API responde 404 e a seção some). O worker roda a rodada; a tela acompanha
// pelo aviso `homologacao` do SSE.

const SITUACAO: Record<SituacaoRodada, string> = {
  pendente: "na fila",
  em_andamento: "em andamento",
  concluida: "concluída",
  falhou: "falhou",
  interrompida: "interrompida",
};

function Homologacao() {
  const [dados, setDados] = useState<DadosHomologacao | null>(null);
  const [indisponivel, setIndisponivel] = useState(false);
  const [aberta, setAberta] = useState<number | null>(null);
  const [versao, setVersao] = useState(0);
  const [erro, setErro] = useState("");

  const carregar = useCallback(() => {
    api
      .homologacao()
      .then((d) => {
        setDados(d);
      })
      .catch((e: unknown) => {
        if (e instanceof ErroApi && e.status === 404) setIndisponivel(true);
        else setErro(mensagemDe(e));
      });
  }, []);
  useEffect(carregar, [carregar]);

  useAvisos(
    useCallback(
      (a: Aviso) => {
        if (a.tipo !== "homologacao" && a.tipo !== "reconectado") return;
        carregar();
        setVersao((v) => v + 1);
      },
      [carregar],
    ),
  );

  if (indisponivel) return null;
  if (!dados) return erro ? <p className="erro">{erro}</p> : null;

  const ocupada = dados.rodadas.some((r) => r.situacao === "pendente" || r.situacao === "em_andamento");

  function gerar(fase: 1 | 2) {
    const n = dados?.consultas_por_fase[String(fase)] ?? fase;
    const plural = n === 1 ? "1 consulta" : `${n} consultas`;
    if (!window.confirm(`Isso abre ${plural} na api-dev e leva até 30 min. Continuar?`)) return;
    setErro("");
    api
      .pedirRodada(fase)
      .then((r) => setAberta(r.id))
      .catch((e: unknown) => setErro(mensagemDe(e)))
      .finally(carregar);
  }

  return (
    <section>
      <h2>Homologação</h2>
      <p className="nota">
        Gera as evidências que a Granatech pede em cada fase, contra <code>{dados.base_granatech}</code>.
        Os webhooks só chegam se a Granatech estiver apontada para{" "}
        {dados.webhook_esperado ? <code>{dados.webhook_esperado}</code> : "este ambiente (SATURDAY_DOMINIO_PUBLICO vazio)"}.
      </p>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      <div className="acoes">
        <button type="button" disabled={ocupada} onClick={() => gerar(1)}>
          Gerar Fase 1
        </button>
        <button type="button" disabled={ocupada} onClick={() => gerar(2)}>
          Gerar Fase 2
        </button>
      </div>

      {dados.rodadas.length === 0 ? (
        <Vazio titulo="Nenhuma rodada." texto="Gere a evidência de uma fase." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Pedida</th>
              <th>Fase</th>
              <th>Situação</th>
              <th>Progresso</th>
              <th>Por</th>
              <th>Terminou</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {dados.rodadas.map((r) => (
              <tr key={r.id}>
                <td>{dataHora(r.criado_em)}</td>
                <td data-rotulo="Fase">{r.fase}</td>
                <td data-rotulo="Situação">
                  <SeloRodada situacao={r.situacao} />
                </td>
                <td data-rotulo="Progresso">
                  <ProgressoRodada estados={estadosDaLista(r)} />
                </td>
                <td data-rotulo="Por">{r.pedido_por ?? "—"}</td>
                <td data-rotulo="Terminou">{dataHora(r.terminado_em)}</td>
                <td className="acoes">
                  <button type="button" onClick={() => setAberta(r.id)} aria-haspopup="dialog">
                    Ver
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {aberta !== null && (
        <DetalheRodada key={aberta} id={aberta} versao={versao} aoFechar={() => setAberta(null)} />
      )}
    </section>
  );
}

// Progresso da rodada: um segmento por item do roteiro da fase. Cor e texto
// juntos (ok, falhou, em curso), nunca só cor.
type EstadoItem = "ok" | "falhou" | "atual" | "falta" | "nao_rodou";

const ESTADO_ITEM: Record<EstadoItem, string> = {
  ok: "ok",
  falhou: "falhou",
  atual: "em curso",
  falta: "aguardando",
  nao_rodou: "não rodou",
};

const ativa = (s: SituacaoRodada) => s === "pendente" || s === "em_andamento";

function estados(total: number, ok: boolean[], situacao: SituacaoRodada): EstadoItem[] {
  return Array.from({ length: total }, (_, i) => {
    if (i < ok.length) return ok[i] ? "ok" : "falhou";
    if (!ativa(situacao)) return "nao_rodou";
    return situacao === "em_andamento" && i === ok.length ? "atual" : "falta";
  });
}

const estadosDaLista = (r: Rodada) => estados(r.progresso.total, r.progresso.ok, r.situacao);

function SeloRodada({ situacao }: { situacao: SituacaoRodada }) {
  return <span className={`selo situacao-rodada-${situacao}`}>{SITUACAO[situacao]}</span>;
}

function ProgressoRodada({ estados }: { estados: EstadoItem[] }) {
  const feitos = estados.filter((e) => e === "ok" || e === "falhou").length;
  const falhas = estados.filter((e) => e === "falhou").length;
  return (
    <span className="progresso-rodada">
      <span
        className="barra-rodada"
        role="progressbar"
        aria-label="Itens da rodada"
        aria-valuemin={0}
        aria-valuemax={estados.length}
        aria-valuenow={feitos}
        aria-valuetext={`${feitos} de ${estados.length} itens${falhas ? `, ${falhas} falhou` : ""}`}
      >
        {estados.map((e, i) => (
          <span key={i} data-estado={e} />
        ))}
      </span>
      <small>
        {feitos}/{estados.length}
        {falhas > 0 && <span className="falhas"> · {falhas} falhou</span>}
      </small>
    </span>
  );
}

const hora = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";

// Situação da rodada no LatticeLoader: a grade roda enquanto o worker trabalha
// e vira check ou cruz no fim; o cronômetro conta desde `iniciado_em`.
const LATTICE: Record<SituacaoRodada, { status: StatusLattice; texto: string }> = {
  pendente: { status: "working", texto: "Na fila" },
  em_andamento: { status: "working", texto: "Rodando" },
  concluida: { status: "done", texto: "Concluída em" },
  falhou: { status: "error", texto: "Falhou após" },
  interrompida: { status: "error", texto: "Interrompida após" },
};

function SituacaoAoVivo({ rodada }: { rodada: RodadaDetalhe }) {
  const rodando = rodada.situacao === "em_andamento";
  const [agora, setAgora] = useState(() => Date.now());
  useEffect(() => {
    if (!rodando) return undefined;
    const id = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(id);
  }, [rodando]);

  const { status, texto } = LATTICE[rodada.situacao];
  const inicio = rodada.iniciado_em ? Date.parse(rodada.iniciado_em) : null;
  const fim = rodada.terminado_em ? Date.parse(rodada.terminado_em) : agora;
  const cor = status === "working" ? "var(--destaque)" : status === "done" ? "var(--ia)" : "var(--erro)";
  return (
    <LatticeLoader
      className="situacao-ao-vivo"
      status={status}
      label={texto}
      doneLabel={texto}
      errorLabel={texto}
      grid={4}
      pattern="sweep"
      shape="round"
      color={cor}
      doneColor="var(--ia)"
      errorColor="var(--erro)"
      cellSize={6}
      gap={2}
      fontSize={16}
      showTimer={inicio !== null}
      elapsed={inicio === null ? 0 : Math.max(0, (fim - inicio) / 1000)}
    />
  );
}

function DetalheRodada({ id, versao, aoFechar }: { id: number; versao: number; aoFechar: () => void }) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [rodada, setRodada] = useState<RodadaDetalhe | null>(null);
  const [erro, setErro] = useState("");

  useEffect(() => {
    dialogo.current?.showModal();
  }, []);

  useEffect(() => {
    api
      .rodada(id)
      .then(setRodada)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, [id, versao]);

  const fechar = () => dialogo.current?.close();

  return (
    // O <dialog> não tem padding: clique direto nele é clique no fundo.
    <dialog
      ref={dialogo}
      className="modal-rodada"
      aria-labelledby="titulo-rodada"
      onClose={aoFechar}
      onClick={(e) => e.target === dialogo.current && fechar()}
    >
      <div className="modal-rodada__corpo">
        <header>
          <h2 id="titulo-rodada">
            Rodada {id}
            {rodada && <span className="fase"> · Fase {rodada.fase}</span>}
          </h2>
          <button type="button" className="fechar" onClick={fechar} aria-label="Fechar">
            <HugeiconsIcon icon={Cancel01Icon} size={20} strokeWidth={2} />
          </button>
        </header>
        <div className="modal-rodada__conteudo">
          {erro ? (
            <p className="erro">{erro}</p>
          ) : !rodada ? (
            <p className="nota">Carregando…</p>
          ) : (
            <ConteudoRodada rodada={rodada} />
          )}
        </div>
        <footer>
          {rodada && !ativa(rodada.situacao) && rodada.passos.length > 0 && (
            <a className="botao principal" href={rodadaZipUrl(rodada.id)}>
              <HugeiconsIcon icon={Download04Icon} size={18} strokeWidth={2} />
              Baixar .zip
            </a>
          )}
          <button type="button" onClick={fechar}>
            Fechar
          </button>
        </footer>
      </div>
    </dialog>
  );
}

function ConteudoRodada({ rodada }: { rodada: RodadaDetalhe }) {
  const lista = estados(
    rodada.itens_previstos.length,
    rodada.itens.map((i) => i.ok),
    rodada.situacao,
  );
  const ultimo = rodada.passos.at(-1);

  return (
    <>
      <SituacaoAoVivo rodada={rodada} />
      <dl className="ficha-granatech">
        <dt>Pedida</dt>
        <dd>
          {dataHora(rodada.criado_em)}
          {rodada.pedido_por && ` por ${rodada.pedido_por}`}
        </dd>
        {rodada.iniciado_em && (
          <>
            <dt>Começou</dt>
            <dd>{dataHora(rodada.iniciado_em)}</dd>
          </>
        )}
        {rodada.terminado_em && (
          <>
            <dt>Terminou</dt>
            <dd>{dataHora(rodada.terminado_em)}</dd>
          </>
        )}
      </dl>

      {rodada.erro && (
        <p className="erro" role="alert">
          Parou antes do fim: {rodada.erro}
        </p>
      )}

      <section aria-labelledby="itens-rodada">
        <div className="titulo-progresso">
          <h3 id="itens-rodada">Itens do roteiro</h3>
          <ProgressoRodada estados={lista} />
        </div>
        <ol className="etapas-rodada">
          {rodada.itens_previstos.map((nome, i) => {
            const item = rodada.itens[i];
            const estado = lista[i];
            return (
              <li key={nome} data-estado={estado}>
                <span className="marcador" aria-hidden="true">
                  {estado === "ok" && <HugeiconsIcon icon={CheckmarkCircle02Icon} size={22} strokeWidth={2} />}
                  {estado === "falhou" && <HugeiconsIcon icon={CancelCircleIcon} size={22} strokeWidth={2} />}
                </span>
                <div>
                  <p className="nome">
                    {nome} <span className="estado">{ESTADO_ITEM[estado]}</span>
                  </p>
                  {item?.observacao && <p className="nota">{item.observacao}</p>}
                  {item && <code className="arquivos">{item.arquivo}</code>}
                  {estado === "atual" && ultimo && (
                    <p className="nota">
                      Último registro às <time>{hora(ultimo.horario)}</time>: <code>{ultimo.arquivo}</code>
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {rodada.passos.length > 0 && (
        <section aria-labelledby="registros-rodada">
          <h3 id="registros-rodada">Registros ({rodada.passos.length})</h3>
          <div className="registros-rodada">
            {rodada.passos.map((p) => (
              <details key={p.arquivo}>
                <summary>
                  <code>{p.arquivo}</code>
                  {p.horario && <time>{hora(p.horario)}</time>}
                </summary>
                <pre>{JSON.stringify(p, null, 2)}</pre>
              </details>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function Filtros({ aoFiltrar }: { aoFiltrar: (f: FiltroGranatech) => void }) {
  const [status, setStatus] = useState("");
  const [desde, setDesde] = useState("");
  const [ate, setAte] = useState("");
  const [cpf, setCpf] = useState("");

  function filtrar(evento: FormEvent) {
    evento.preventDefault();
    aoFiltrar({ status: status.trim().toUpperCase(), desde, ate, cpf: cpf.replace(/\D/g, "") });
  }

  return (
    <form className="form-usuario" onSubmit={filtrar}>
      <label>
        Status
        <input value={status} onChange={(e) => setStatus(e.target.value)} placeholder="ex.: PAYED" />
      </label>
      <label>
        De
        <input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
      </label>
      <label>
        Até
        <input type="date" value={ate} onChange={(e) => setAte(e.target.value)} />
      </label>
      <label>
        CPF completo
        <input
          value={cpf}
          onChange={(e) => setCpf(e.target.value)}
          inputMode="numeric"
          autoComplete="off"
        />
      </label>
      <button type="submit">Filtrar</button>
    </form>
  );
}

function SemConversa({ conversa }: { conversa: string | null }) {
  return conversa ? (
    <Link to={`/conversas/${conversa}`}>abrir conversa</Link>
  ) : (
    <span className="nota">sem conversa</span>
  );
}

function ListaConsultas({
  linhas,
  selecionar,
}: {
  linhas: ConsultaGranatech[] | null;
  selecionar: (id: number) => void;
}) {
  if (!linhas) return <p className="centro">Carregando…</p>;
  if (linhas.length === 0) return <Vazio titulo="Nenhuma consulta." texto="Mude os filtros." />;
  return (
    <table>
      <thead>
        <tr>
          <th>Criada</th>
          <th>CPF</th>
          <th>Status</th>
          <th>Detalhe</th>
          <th>Conversa</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {linhas.map((c) => (
          <tr key={c.id}>
            <td>{dataHora(c.criada_em)}</td>
            <td data-rotulo="CPF">{c.cpf}</td>
            <td data-rotulo="Status">{c.status}</td>
            <td data-rotulo="Detalhe">{c.tem_detalhe ? "gravado" : "—"}</td>
            <td data-rotulo="Conversa">
              <SemConversa conversa={c.conversa_id} />
            </td>
            <td className="acoes">
              <button type="button" onClick={() => selecionar(c.id)}>
                Ver
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ListaPropostas({
  linhas,
  selecionar,
}: {
  linhas: PropostaGranatech[] | null;
  selecionar: (id: number) => void;
}) {
  if (!linhas) return <p className="centro">Carregando…</p>;
  if (linhas.length === 0) return <Vazio titulo="Nenhuma proposta." texto="Mude os filtros." />;
  return (
    <table>
      <thead>
        <tr>
          <th>Intenção</th>
          <th>CPF</th>
          <th>Envio</th>
          <th>Status</th>
          <th>Parcelas</th>
          <th>Conversa</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {linhas.map((p) => (
          <tr key={p.id}>
            <td>{dataHora(p.intencao_em)}</td>
            <td data-rotulo="CPF">{p.cpf}</td>
            <td data-rotulo="Envio">{p.estado_envio}</td>
            <td data-rotulo="Status">
              {p.status ?? "—"}
              {p.tipo_notificacao && <small> ({p.tipo_notificacao})</small>}
            </td>
            <td data-rotulo="Parcelas">
              {p.numero_parcelas} × {reais(p.valor_parcela)}
            </td>
            <td data-rotulo="Conversa">
              <SemConversa conversa={p.conversa_id} />
            </td>
            <td className="acoes">
              <button type="button" onClick={() => selecionar(p.id)}>
                Ver
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// O detalhe abre abaixo da lista: leva a tela até ele quando outro item é aberto.
function useAoAbrir(id: number | undefined) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (id !== undefined) ref.current?.scrollIntoView({ block: "start" });
  }, [id]);
  return ref;
}

function Historico({ eventos }: { eventos: EventoGranatech[] }) {
  if (eventos.length === 0) return <p className="nota">Nenhum evento recebido ainda.</p>;
  return (
    <ol className="historico-granatech">
      {eventos.map((e, i) => (
        // O histórico só cresce: a posição identifica o evento.
        <li key={i}>
          <time>{dataHora(e.recebido_em)}</time> {e.status ?? "—"}
          {e.tipo_notificacao && <small> ({e.tipo_notificacao})</small>}
          {e.origem === "painel" && <small> pelo painel</small>}
          {e.informacoes != null && (
            <pre className="nota">{JSON.stringify(e.informacoes, null, 2)}</pre>
          )}
        </li>
      ))}
    </ol>
  );
}

function Cpf({ consultaId, mascarado }: { consultaId: number; mascarado: string }) {
  const [valor, setValor] = useState<string | null>(null);
  const [revelando, setRevelando] = useState(false);
  const [erro, setErro] = useState("");
  return (
    <span>
      {valor ?? mascarado}{" "}
      {valor === null && (
        <button
          type="button"
          className="link"
          disabled={revelando}
          onClick={() => {
            // Cada clique grava auditoria: um pedido por vez.
            setRevelando(true);
            setErro("");
            api
              .revelarCpfGranatech(consultaId)
              .then((r) => setValor(r.valor))
              .catch((e: unknown) => setErro(`não deu para revelar: ${mensagemDe(e)}`))
              .finally(() => setRevelando(false));
          }}
        >
          Revelar
        </button>
      )}
      {erro && (
        <small className="erro" role="alert">
          {" "}
          {erro}
        </small>
      )}
    </span>
  );
}

function BotaoAcao({
  acoes,
  nome,
  rotulo: texto,
  onClick,
  perigo,
}: {
  acoes: Acoes;
  nome: string;
  rotulo: string;
  onClick: () => void;
  perigo?: boolean;
}) {
  const motivo = acoes[nome];
  return (
    <button
      type="button"
      className={perigo ? "perigo" : undefined}
      disabled={motivo != null}
      title={motivo ?? undefined}
      onClick={onClick}
    >
      {texto}
      {motivo != null && <small> ({motivo})</small>}
    </button>
  );
}

function DetalheConsulta({
  id,
  versao,
  gestor,
  agir,
  abrirProposta,
}: {
  id: number;
  versao: number;
  gestor: boolean;
  agir: Agir;
  abrirProposta: (id: number) => void;
}) {
  const [c, setC] = useState<ConsultaGranatechDetalhe | null>(null);
  const secao = useAoAbrir(c?.id);
  // Falhar ao recarregar mantém o último detalhe; sem nenhum, diz por quê.
  const [erroCarga, setErroCarga] = useState("");
  const [tentativa, setTentativa] = useState(0);
  useEffect(() => {
    api
      .consultaGranatech(id)
      .then((d) => {
        setC(d);
        setErroCarga("");
      })
      .catch((e: unknown) => setErroCarga(mensagemDe(e)));
  }, [id, versao, tentativa]);
  if (!c)
    return erroCarga ? (
      <Falha
        titulo="Não deu para abrir o detalhe."
        texto={erroCarga}
        aoTentar={() => setTentativa((t) => t + 1)}
      />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <section ref={secao}>
      <h2>Consulta {c.id_externo}</h2>
      <dl className="ficha-granatech">
        <dt>CPF</dt>
        <dd>
          <Cpf consultaId={c.id} mascarado={c.cpf} />
        </dd>
        <dt>Status</dt>
        <dd>{c.status}</dd>
        <dt>Etapa da conversa</dt>
        <dd>{c.etapa ? rotulo(ETAPAS, c.etapa) : "—"}</dd>
        <dt>Idade e sexo</dt>
        <dd>
          {c.idade ?? "—"} · {c.sexo ?? "—"}
        </dd>
        <dt>Conversa</dt>
        <dd>
          <SemConversa conversa={c.conversa_id} />
        </dd>
        <dt>Propostas</dt>
        <dd>
          {c.propostas.length === 0
            ? "—"
            : c.propostas.map((p) => (
                <button key={p} type="button" className="link" onClick={() => abrirProposta(p)}>
                  #{p}
                </button>
              ))}
        </dd>
      </dl>

      <h3>Vínculos</h3>
      {c.vinculos.length === 0 ? (
        <p className="nota">Detalhe ainda não gravado.</p>
      ) : (
        <ul>
          {c.vinculos.map((v, i) => (
            <li key={i}>
              {v.nome_empregador ?? "—"} ({v.documento_empregador ?? "—"}) · margem {reais(v.margem)}
              {v.elegivel_empregador === false && <small> · empregador não elegível</small>}
              {v.produtos && v.produtos.length > 0 && (
                <small> · produtos: {v.produtos.map((p) => p.nome ?? p.id).join(", ")}</small>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3>Linha do tempo</h3>
      <Historico eventos={c.historico} />

      {gestor && (
        <div className="acoes">
          <BotaoAcao
            acoes={c.acoes}
            nome="atualizar_detalhe"
            rotulo="Atualizar detalhe"
            onClick={() =>
              agir(
                () => api.atualizarDetalhe(c.id),
                (r) =>
                  (r as { pronto: boolean }).pronto
                    ? "Detalhe gravado; a jornada seguiu."
                    : "A Granatech ainda não tem as margens.",
              )
            }
          />
        </div>
      )}
    </section>
  );
}

function DetalheProposta({
  id,
  versao,
  gestor,
  agir,
  abrirConsulta,
}: {
  id: number;
  versao: number;
  gestor: boolean;
  agir: Agir;
  abrirConsulta: (id: number) => void;
}) {
  const [p, setP] = useState<PropostaGranatechDetalhe | null>(null);
  const [painel, setPainel] = useState<"cancelar" | "conta" | null>(null);
  const secao = useAoAbrir(p?.id);
  // Falhar ao recarregar mantém o último detalhe; sem nenhum, diz por quê.
  const [erroCarga, setErroCarga] = useState("");
  const [tentativa, setTentativa] = useState(0);
  useEffect(() => {
    api
      .propostaGranatech(id)
      .then((d) => {
        setP(d);
        setErroCarga("");
      })
      .catch((e: unknown) => setErroCarga(mensagemDe(e)));
  }, [id, versao, tentativa]);
  if (!p)
    return erroCarga ? (
      <Falha
        titulo="Não deu para abrir o detalhe."
        texto={erroCarga}
        aoTentar={() => setTentativa((t) => t + 1)}
      />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <section ref={secao}>
      <h2>Proposta {p.id_externo ?? `#${p.id} (sem id na Granatech)`}</h2>
      <dl className="ficha-granatech">
        <dt>CPF</dt>
        <dd>
          <Cpf consultaId={p.consulta_id} mascarado={p.cpf} />
        </dd>
        <dt>Envio</dt>
        <dd>{p.estado_envio}</dd>
        <dt>Status</dt>
        <dd>
          {p.status ?? "—"}
          {p.tipo_notificacao && <small> ({p.tipo_notificacao})</small>}
        </dd>
        <dt>Parcelas</dt>
        <dd>
          {p.numero_parcelas} × {reais(p.valor_parcela)}
        </dd>
        <dt>Etapa da conversa</dt>
        <dd>{p.etapa ? rotulo(ETAPAS, p.etapa) : "—"}</dd>
        <dt>Consulta</dt>
        <dd>
          <button type="button" className="link" onClick={() => abrirConsulta(p.consulta_id)}>
            #{p.consulta_id}
          </button>
        </dd>
        <dt>Conversa</dt>
        <dd>
          <SemConversa conversa={p.conversa_id} />
        </dd>
      </dl>

      {p.oferta && (
        <>
          <h3>Oferta aceita</h3>
          <pre className="nota">{JSON.stringify(p.oferta, null, 2)}</pre>
        </>
      )}

      <h3>Linha do tempo</h3>
      <Historico eventos={p.historico} />

      {gestor && (
        <div className="acoes">
          <BotaoAcao
            acoes={p.acoes}
            nome="reconciliar"
            rotulo="Reconciliar"
            onClick={() =>
              agir(
                () => api.reconciliar(p.id),
                (r) =>
                  (r as { achada: boolean }).achada
                    ? "Proposta achada; a conversa voltou para a IA e a jornada seguiu."
                    : "Não está na listagem da Granatech. A conversa segue aguardando humano.",
              )
            }
          />
          <BotaoAcao
            acoes={p.acoes}
            nome="reenviar_link"
            rotulo="Reenviar link de biometria"
            onClick={() => agir(() => api.reenviarLink(p.id), "Link reenviado ao cliente.")}
          />
          {p.conta_ativa && (
            <BotaoAcao
              acoes={p.acoes}
              nome="corrigir_conta"
              rotulo="Corrigir conta"
              onClick={() => setPainel("conta")}
            />
          )}
          <BotaoAcao
            acoes={p.acoes}
            nome="cancelar"
            rotulo="Cancelar proposta"
            perigo
            onClick={() => setPainel("cancelar")}
          />
        </div>
      )}
      {painel === "cancelar" && (
        <Cancelar
          aoConfirmar={(motivo) => {
            setPainel(null);
            agir(
              () => api.cancelarProposta(p.id, motivo),
              "Cancelamento pedido. O cliente é avisado quando a Granatech confirmar.",
            );
          }}
          aoFechar={() => setPainel(null)}
        />
      )}
      {painel === "conta" && (
        <CorrigirConta
          aoEnviar={(conta) => {
            setPainel(null);
            agir(() => api.corrigirConta(p.id, conta), "Conta enviada à Granatech.");
          }}
          aoFechar={() => setPainel(null)}
        />
      )}
    </section>
  );
}

function Cancelar({
  aoConfirmar,
  aoFechar,
}: {
  aoConfirmar: (motivo: string) => void;
  aoFechar: () => void;
}) {
  const [motivo, setMotivo] = useState("");
  function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!window.confirm("Cancelar a proposta na Granatech? Não dá para desfazer.")) return;
    aoConfirmar(motivo.trim());
  }
  return (
    <form className="form-usuario" onSubmit={enviar}>
      <h3>Cancelar proposta</h3>
      <label>
        Motivo (fica na auditoria)
        <textarea
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          minLength={3}
          maxLength={500}
          required
        />
      </label>
      <button type="submit" className="perigo">
        Cancelar proposta
      </button>
      <button type="button" onClick={aoFechar}>
        Voltar
      </button>
    </form>
  );
}

function CorrigirConta({
  aoEnviar,
  aoFechar,
}: {
  aoEnviar: (conta: ContaNova) => void;
  aoFechar: () => void;
}) {
  const [conta, setConta] = useState<ContaNova>(CONTA_VAZIA);

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    aoEnviar(conta);
  }

  return (
    <form className="form-usuario" onSubmit={enviar}>
      <h3>Corrigir conta</h3>
      <p className="nota">A conta precisa ser do próprio cliente.</p>
      <CamposConta conta={conta} mudar={setConta} />
      <button type="submit">Enviar à Granatech</button>
      <button type="button" onClick={aoFechar}>
        Voltar
      </button>
    </form>
  );
}
