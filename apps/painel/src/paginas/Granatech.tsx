import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { Vazio } from "../componentes/Vazio";
import {
  type Acoes,
  api,
  type ConsultaGranatech,
  type ConsultaGranatechDetalhe,
  type ContaNova,
  type Cota,
  ErroApi,
  type Eu,
  type EventoGranatech,
  type FiltroGranatech,
  type PropostaGranatech,
  type PropostaGranatechDetalhe,
} from "../api";
import { ETAPAS, rotulo } from "../rotulos";
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

  const agir: Agir = (acao, feito) => {
    setErro("");
    setAviso("");
    acao()
      .then((r) => setAviso(typeof feito === "string" ? feito : feito(r)))
      .catch((e: unknown) => setErro(mensagemDe(e)))
      .finally(() => {
        carregar();
        setVersao((v) => v + 1);
      });
  };

  return (
    <div className="canais granatech">
      <h1 className="titulo-tela">Granatech</h1>
      <CotaGranatech versao={versao} />
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
    </div>
  );
}

function CotaGranatech({ versao }: { versao: number }) {
  const [cota, setCota] = useState<Cota | null>(null);
  useEffect(() => {
    api.cota().then(setCota).catch(() => setCota(null));
  }, [versao]);
  if (!cota) return null;
  return (
    <p className="cota">
      Cota hoje {cota.dia.usadas}/{cota.dia.teto} · no mês {cota.mes.usadas}/{cota.mes.teto}
    </p>
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
              {p.numero_parcelas} × R$ {p.valor_parcela}
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
  return (
    <span>
      {valor ?? mascarado}{" "}
      {valor === null && (
        <button
          type="button"
          onClick={() =>
            api
              .revelarCpfGranatech(consultaId)
              .then((r) => setValor(r.valor))
              .catch(() => undefined)
          }
        >
          Revelar
        </button>
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
  useEffect(() => {
    api.consultaGranatech(id).then(setC).catch(() => setC(null));
  }, [id, versao]);
  if (!c) return null;

  return (
    <section>
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
                <button key={p} type="button" onClick={() => abrirProposta(p)}>
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
              {v.nome_empregador ?? "—"} ({v.documento_empregador ?? "—"}) · margem R${" "}
              {String(v.margem ?? "—")}
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
  useEffect(() => {
    api.propostaGranatech(id).then(setP).catch(() => setP(null));
  }, [id, versao]);
  if (!p) return null;

  return (
    <section>
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
          {p.numero_parcelas} × R$ {p.valor_parcela}
        </dd>
        <dt>Etapa da conversa</dt>
        <dd>{p.etapa ? rotulo(ETAPAS, p.etapa) : "—"}</dd>
        <dt>Consulta</dt>
        <dd>
          <button type="button" onClick={() => abrirConsulta(p.consulta_id)}>
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
  const [bancos, setBancos] = useState<{ codigo: string; nome: string }[] | null>(null);
  const [erro, setErro] = useState("");
  const [conta, setConta] = useState<ContaNova>({
    banco_codigo: "",
    agencia: "",
    digito_agencia: "",
    numero_conta: "",
    digito_conta: "",
    tipo_conta: "conta_corrente",
  });
  useEffect(() => {
    api
      .bancosGranatech()
      .then(setBancos)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, []);
  const campo = (nome: keyof ContaNova) => ({
    value: conta[nome],
    onChange: (e: { target: { value: string } }) => setConta({ ...conta, [nome]: e.target.value }),
  });

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    aoEnviar(conta);
  }

  return (
    <form className="form-usuario" onSubmit={enviar}>
      <h3>Corrigir conta</h3>
      <p className="nota">A conta precisa ser do próprio cliente.</p>
      {erro && <p className="erro">{erro}</p>}
      <label>
        Banco
        <select {...campo("banco_codigo")} required>
          <option value="">{bancos ? "Escolha" : "Carregando…"}</option>
          {bancos?.map((b) => (
            <option key={b.codigo} value={b.codigo}>
              {b.codigo} · {b.nome}
            </option>
          ))}
        </select>
      </label>
      <label>
        Agência
        <input {...campo("agencia")} inputMode="numeric" pattern="\d{1,6}" required />
      </label>
      <label>
        Dígito da agência
        <input {...campo("digito_agencia")} pattern="[0-9Xx]?" maxLength={1} />
      </label>
      <label>
        Conta
        <input {...campo("numero_conta")} inputMode="numeric" pattern="\d{1,20}" required />
      </label>
      <label>
        Dígito da conta
        <input {...campo("digito_conta")} pattern="[0-9Xx]" maxLength={1} required />
      </label>
      <label>
        Tipo
        <select {...campo("tipo_conta")}>
          <option value="conta_corrente">Conta corrente</option>
          <option value="conta_poupanca">Conta poupança</option>
        </select>
      </label>
      <button type="submit">Enviar à Granatech</button>
      <button type="button" onClick={aoFechar}>
        Voltar
      </button>
    </form>
  );
}
