import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ErroApi,
  type ModeloDoCatalogo,
  type ModelosAgente,
  type PapelModelo,
  type ResultadoTeste,
  type VersaoAgente,
} from "../api";
import { Dialogo } from "../componentes/Dialogo";
import { Falha } from "../componentes/Falha";
import { duracao } from "../componentes/ItemTurno";
import { Vazio } from "../componentes/Vazio";
import { dolar, NOS, rotulo, tokens } from "../rotulos";
import { useAvisos } from "../tempoReal";

type Rascunho = Partial<Record<PapelModelo, string>>;
type Papel = ModelosAgente["papeis"][number];

const mensagem = (e: unknown) => (e instanceof ErroApi ? e.message : "falha ao carregar");
const dataHora = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const porMilhao = (v: number | null) => (v === null ? "—" : `${dolar(v)}/M`);
const LIMITE_LINHAS = 80;
const MAX_COMPARAR = 3;
const JSON_ESTRUTURADO = ["response_format", "structured_outputs"];

// O modelo serve para a etapa? Mesma regra da API (`agente_modelos._validar`).
function serve(m: ModeloDoCatalogo, papel: Papel): boolean {
  if (papel.exige_entrada && !m.entrada.includes(papel.exige_entrada)) return false;
  return m.parametros.length === 0 || m.parametros.some((p) => JSON_ESTRUTURADO.includes(p));
}

function useModelos() {
  const [dados, setDados] = useState<ModelosAgente | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(() => {
    api
      .modelosAgente()
      .then((d) => {
        setDados(d);
        setErro("");
      })
      .catch((e: unknown) => setErro(mensagem(e)));
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (aviso) => (aviso.tipo === "agente" || aviso.tipo === "reconectado") && carregar(),
      [carregar],
    ),
  );
  return { dados, erro, carregar };
}

// Aviso antes de aplicar: a troca vale no próximo turno; os que rodam terminam como estão.
function AvisoEmAndamento({ n }: { n: number }) {
  return (
    <p className="aviso-mudanca" role="note">
      <strong>Vale a partir do próximo turno.</strong>{" "}
      {n > 0
        ? `Agora há ${n} ${n === 1 ? "turno" : "turnos"} em andamento: ${n === 1 ? "ele termina" : "eles terminam"} com a configuração atual.`
        : "Nenhum turno está rodando agora."}
    </p>
  );
}

// ------------------------------------------------------------------ modelos

export function AbaModelos() {
  const { dados, erro, carregar } = useModelos();
  const [rascunho, setRascunho] = useState<Rascunho>({});
  const [confirmar, setConfirmar] = useState(false);
  const [testando, setTestando] = useState<{ papel: Papel; modelo: string } | null>(null);
  const [comparar, setComparar] = useState<string[]>([]);
  const [atualizando, setAtualizando] = useState(false);
  const [aviso, setAviso] = useState("");

  if (!dados)
    return erro ? (
      <Falha titulo="Não deu para carregar os modelos." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  const valor = (p: Papel) => rascunho[p.papel] ?? p.modelo;
  const mudancas = dados.papeis.filter((p) => valor(p) !== p.modelo);
  const catalogo = dados.catalogo.modelos;
  const porId = new Map(catalogo.map((m) => [m.id, m]));

  function atualizarCatalogo() {
    setAtualizando(true);
    setAviso("");
    api
      .atualizarCatalogo()
      .then((r) => {
        setAviso(`Catálogo atualizado: ${r.modelos} modelos.`);
        carregar();
      })
      .catch((e: unknown) => setAviso(`Não deu para atualizar: ${mensagem(e)}`))
      .finally(() => setAtualizando(false));
  }

  return (
    <div className="modelos-agente">
      <section className="faixa-versao">
        <p>
          {dados.vigente ? (
            <>
              <strong>Versão {dados.vigente.versao}</strong> vigente desde{" "}
              {dataHora(dados.vigente.criada_em)}
              {dados.vigente.autor && `, por ${dados.vigente.autor}`}
              {dados.vigente.nota && ` — “${dados.vigente.nota}”`}
            </>
          ) : (
            <>
              <strong>Nenhuma versão salva.</strong> Valem as variáveis de ambiente do servidor.
            </>
          )}
        </p>
        <p className="nota">
          Preços e limites: OpenRouter (<code>{dados.catalogo.fonte}</code>),{" "}
          {dados.catalogo.buscado_em
            ? `lidos em ${dataHora(dados.catalogo.buscado_em)}`
            : "ainda não lidos"}
          . Latência: medida nas nossas chamadas dos últimos {dados.latencia_dias} dias.
        </p>
        {dados.pode_editar && (
          <button type="button" onClick={atualizarCatalogo} disabled={atualizando}>
            {atualizando ? "Atualizando…" : "Atualizar catálogo"}
          </button>
        )}
        {aviso && (
          <p className="nota" role="status">
            {aviso}
          </p>
        )}
        {!dados.pode_editar && (
          <p className="nota">Só quem tem a permissão “editar o agente” troca os modelos.</p>
        )}
      </section>

      <div className="papeis-modelo">
        {dados.papeis.map((p) => (
          <CartaoPapel
            key={p.papel}
            papel={p}
            dados={dados}
            valor={valor(p)}
            mudar={(v) =>
              setRascunho((r) => {
                const novo = { ...r, [p.papel]: v };
                if (v === p.modelo) delete novo[p.papel];
                return novo;
              })
            }
            testar={() => setTestando({ papel: p, modelo: valor(p) })}
            info={porId.get(valor(p)) ?? null}
          />
        ))}
      </div>

      <Catalogo
        dados={dados}
        comparar={comparar}
        mudarComparar={setComparar}
        atualizar={dados.pode_editar ? atualizarCatalogo : null}
      />

      {mudancas.length > 0 && (
        <div className="barra-rascunho" role="region" aria-label="Alterações não salvas">
          <span>
            {mudancas.length} {mudancas.length === 1 ? "alteração não salva" : "alterações não salvas"}
          </span>
          <button type="button" onClick={() => setRascunho({})}>
            Cancelar
          </button>
          <button type="button" className="principal" onClick={() => setConfirmar(true)}>
            Salvar
          </button>
        </div>
      )}

      {confirmar && (
        <ConfirmarSalvar
          dados={dados}
          mudancas={mudancas.map((p) => ({ papel: p, de: p.modelo, para: valor(p) }))}
          fechar={() => setConfirmar(false)}
          salvo={() => {
            setConfirmar(false);
            setRascunho({});
            carregar();
          }}
          salvar={(nota) =>
            api.salvarVersao(
              dados.vigente?.versao ?? null,
              Object.fromEntries(mudancas.map((p) => [p.papel, valor(p)])),
              nota,
            )
          }
        />
      )}
      {testando && (
        <TestarModelo
          papel={testando.papel}
          modelo={testando.modelo}
          fechar={() => setTestando(null)}
        />
      )}
    </div>
  );
}

function CartaoPapel({
  papel,
  dados,
  valor,
  mudar,
  testar,
  info,
}: {
  papel: Papel;
  dados: ModelosAgente;
  valor: string;
  mudar: (v: string) => void;
  testar: () => void;
  info: ModeloDoCatalogo | null;
}) {
  const opcoes = useMemo(
    () => dados.catalogo.modelos.filter((m) => serve(m, papel)),
    [dados.catalogo.modelos, papel],
  );
  const id = `modelo-${papel.papel}`;
  const latencia = dados.latencia[valor];
  const usaCatalogo = papel.do_catalogo && opcoes.length > 0;
  const provedor =
    papel.papel === "jev" ? "OpenRouter Decisions" : papel.papel === "transcricao" ? dados.transcricao_provedor : null;

  return (
    <section className={valor !== papel.modelo ? "papel-modelo alterado" : "papel-modelo"}>
      <header>
        <h3>{papel.rotulo}</h3>
        <p className="nota">
          {papel.no ? `Nó do grafo: ${rotulo(NOS, papel.no)}` : "Entrada do canal (áudio do cliente)"}
          {" · "}
          {papel.origem === "versao"
            ? `da versão ${dados.vigente?.versao}`
            : `do ambiente (${papel.variavel})`}
        </p>
      </header>
      <label htmlFor={id}>Modelo</label>
      {usaCatalogo ? (
        <select id={id} value={valor} onChange={(e) => mudar(e.target.value)} disabled={!dados.pode_editar}>
          {!opcoes.some((m) => m.id === valor) && (
            <option value={valor}>{valor || "— nenhum —"} (fora do catálogo)</option>
          )}
          {opcoes.map((m) => (
            <option key={m.id} value={m.id}>
              {m.nome} · {porMilhao(m.preco_entrada)}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          value={valor}
          onChange={(e) => mudar(e.target.value.trim())}
          disabled={!dados.pode_editar}
          maxLength={128}
          spellCheck={false}
          placeholder="id do modelo"
        />
      )}
      {!valor && <p className="erro">Sem modelo: esta etapa fica desligada.</p>}
      {papel.do_catalogo && opcoes.length === 0 && (
        <p className="nota">
          Sem catálogo lido: digite o id. Atualize o catálogo para ver preços e escolher na lista.
        </p>
      )}
      {provedor && (
        <p className="nota">
          Provedor próprio ({provedor}): fora do catálogo da OpenRouter, sem preço publicado aqui.
        </p>
      )}
      <dl className="ficha-modelo">
        {info && (
          <>
            <div>
              <dt>Entrada</dt>
              <dd>{porMilhao(info.preco_entrada)}</dd>
            </div>
            <div>
              <dt>Saída</dt>
              <dd>{porMilhao(info.preco_saida)}</dd>
            </div>
            <div>
              <dt>Contexto</dt>
              <dd>{info.contexto ? tokens(info.contexto) : "—"}</dd>
            </div>
            <div>
              <dt>Máx. de saída</dt>
              <dd>{info.max_saida ? tokens(info.max_saida) : "—"}</dd>
            </div>
            <div>
              <dt>Aceita</dt>
              <dd>{info.entrada.join(", ")}</dd>
            </div>
          </>
        )}
        <div>
          <dt>Latência medida</dt>
          <dd>
            {latencia
              ? `${duracao(latencia.media_ms)} (p95 ${duracao(latencia.p95_ms)}, ${latencia.chamadas} chamadas)`
              : "sem chamadas no período"}
          </dd>
        </div>
      </dl>
      {dados.pode_testar && papel.papel !== "transcricao" && valor && (
        <button type="button" onClick={testar}>
          Testar {valor === papel.modelo ? "este modelo" : "antes de salvar"}
        </button>
      )}
    </section>
  );
}

function Catalogo({
  dados,
  comparar,
  mudarComparar,
  atualizar,
}: {
  dados: ModelosAgente;
  comparar: string[];
  mudarComparar: (ids: string[]) => void;
  atualizar: (() => void) | null;
}) {
  const [busca, setBusca] = useState("");
  const [soImagem, setSoImagem] = useState(false);
  const [ordem, setOrdem] = useState<"preco" | "contexto" | "nome">("preco");
  const todos = dados.catalogo.modelos;

  const lista = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const filtrados = todos.filter(
      (m) =>
        (!termo || m.id.toLowerCase().includes(termo) || m.nome.toLowerCase().includes(termo)) &&
        (!soImagem || m.entrada.includes("image")),
    );
    const chave = {
      preco: (m: ModeloDoCatalogo) => m.preco_entrada ?? Infinity,
      contexto: (m: ModeloDoCatalogo) => -(m.contexto ?? 0),
      nome: () => 0,
    }[ordem];
    return filtrados.sort((a, b) => chave(a) - chave(b) || a.nome.localeCompare(b.nome));
  }, [todos, busca, soImagem, ordem]);

  if (todos.length === 0)
    return (
      <section className="catalogo">
        <h2>Modelos disponíveis</h2>
        <Vazio
          titulo="Nenhum modelo no catálogo."
          texto={
            atualizar
              ? "Leia o catálogo da OpenRouter para ver preços, limites e capacidades."
              : "Peça a quem pode editar o agente para atualizar o catálogo."
          }
        />
      </section>
    );

  const alternar = (id: string) =>
    mudarComparar(
      comparar.includes(id)
        ? comparar.filter((c) => c !== id)
        : comparar.length < MAX_COMPARAR
          ? [...comparar, id]
          : comparar,
    );
  const escolhidos = comparar.map((id) => todos.find((m) => m.id === id)).filter((m) => !!m);

  return (
    <section className="catalogo">
      <h2>
        Modelos disponíveis <span className="contagem">· {todos.length}</span>
      </h2>
      <div className="execucoes-filtros">
        <label>
          Buscar
          <input
            type="search"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder="nome ou id"
          />
        </label>
        <label>
          Ordenar por
          <select value={ordem} onChange={(e) => setOrdem(e.target.value as typeof ordem)}>
            <option value="preco">Menor preço de entrada</option>
            <option value="contexto">Maior contexto</option>
            <option value="nome">Nome</option>
          </select>
        </label>
        <label className="opcao">
          <input type="checkbox" checked={soImagem} onChange={(e) => setSoImagem(e.target.checked)} />
          Só os que leem imagem
        </label>
      </div>

      {escolhidos.length > 0 && (
        <div className="comparar">
          <h3>Comparando {escolhidos.length} de até {MAX_COMPARAR}</h3>
          <div className="tabela-rolavel">
            <table>
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  {escolhidos.map((m) => (
                    <th key={m.id} scope="col">
                      {m.nome}
                      <button type="button" className="link" onClick={() => alternar(m.id)}>
                        tirar
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["Entrada", (m) => porMilhao(m.preco_entrada)],
                    ["Saída", (m) => porMilhao(m.preco_saida)],
                    ["Imagem", (m) => (m.preco_imagem ? porMilhao(m.preco_imagem) : "—")],
                    ["Contexto", (m) => (m.contexto ? tokens(m.contexto) : "—")],
                    ["Máx. de saída", (m) => (m.max_saida ? tokens(m.max_saida) : "—")],
                    ["Aceita", (m) => m.entrada.join(", ")],
                    [
                      "Resposta em JSON",
                      (m) => (m.parametros.some((p) => JSON_ESTRUTURADO.includes(p)) ? "sim" : "não"),
                    ],
                    [
                      "Latência medida",
                      (m) =>
                        dados.latencia[m.id] ? duracao(dados.latencia[m.id].media_ms) : "sem dados",
                    ],
                  ] as [string, (m: ModeloDoCatalogo) => string][]
                ).map(([nome, f]) => (
                  <tr key={nome}>
                    <th scope="row">{nome}</th>
                    {escolhidos.map((m) => (
                      <td key={m.id}>{f(m)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {lista.length === 0 ? (
        <Vazio titulo="Nenhum modelo com esse filtro." texto="Tente outro nome ou tire o filtro." />
      ) : (
        <div className="tabela-rolavel">
          <table className="tabela-catalogo">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr">Comparar</span>
                </th>
                <th scope="col">Modelo</th>
                <th scope="col" className="num">
                  Entrada
                </th>
                <th scope="col" className="num">
                  Saída
                </th>
                <th scope="col" className="num">
                  Contexto
                </th>
                <th scope="col">Aceita</th>
              </tr>
            </thead>
            <tbody>
              {lista.slice(0, LIMITE_LINHAS).map((m) => (
                <tr key={m.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Comparar ${m.nome}`}
                      checked={comparar.includes(m.id)}
                      disabled={!comparar.includes(m.id) && comparar.length >= MAX_COMPARAR}
                      onChange={() => alternar(m.id)}
                    />
                  </td>
                  <td>
                    {m.nome}
                    <code>{m.id}</code>
                  </td>
                  <td className="num">{porMilhao(m.preco_entrada)}</td>
                  <td className="num">{porMilhao(m.preco_saida)}</td>
                  <td className="num">{m.contexto ? tokens(m.contexto) : "—"}</td>
                  <td>{m.entrada.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lista.length > LIMITE_LINHAS && (
        <p className="nota">
          Mostrando {LIMITE_LINHAS} de {lista.length}. Refine a busca para ver os outros.
        </p>
      )}
    </section>
  );
}

function ConfirmarSalvar({
  dados,
  mudancas,
  salvar,
  salvo,
  fechar,
}: {
  dados: ModelosAgente;
  mudancas: { papel: Papel; de: string; para: string }[];
  salvar: (nota: string) => Promise<unknown>;
  salvo: () => void;
  fechar: () => void;
}) {
  const [nota, setNota] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  function confirmar() {
    setEnviando(true);
    setErro("");
    salvar(nota)
      .then(salvo)
      .catch((e: unknown) => setErro(mensagem(e)))
      .finally(() => setEnviando(false));
  }

  return (
    <Dialogo
      titulo="Salvar nova versão"
      aoFechar={fechar}
      rodape={
        <>
          <button type="button" onClick={fechar}>
            Voltar
          </button>
          <button type="button" className="principal" onClick={confirmar} disabled={enviando}>
            {enviando ? "Salvando…" : `Salvar versão ${(dados.vigente?.versao ?? 0) + 1}`}
          </button>
        </>
      }
    >
      <AvisoEmAndamento n={dados.em_andamento} />
      <ul className="lista-mudancas">
        {mudancas.map((m) => (
          <li key={m.papel.papel}>
            <strong>{m.papel.rotulo}</strong>
            <span>
              <code>{m.de || "—"}</code> → <code>{m.para || "—"}</code>
            </span>
          </li>
        ))}
      </ul>
      <label>
        Nota (opcional)
        <input value={nota} onChange={(e) => setNota(e.target.value)} maxLength={280} />
      </label>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
    </Dialogo>
  );
}

function TestarModelo({ papel, modelo, fechar }: { papel: Papel; modelo: string; fechar: () => void }) {
  const [texto, setTexto] = useState(
    papel.papel === "jev" ? "quero falar com um atendente" : "Vocês cobram alguma taxa antes?",
  );
  const [resultado, setResultado] = useState<ResultadoTeste | null>(null);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  function testar() {
    setEnviando(true);
    setErro("");
    setResultado(null);
    api
      .testarModelo(papel.papel, modelo, texto)
      .then(setResultado)
      .catch((e: unknown) => setErro(mensagem(e)))
      .finally(() => setEnviando(false));
  }

  return (
    <Dialogo
      titulo={`Testar ${modelo}`}
      aoFechar={fechar}
      rodape={
        <button type="button" className="principal" onClick={testar} disabled={enviando || !texto.trim()}>
          {enviando ? "Testando…" : "Testar"}
        </button>
      }
    >
      <p className="nota">
        Chamada real e paga à OpenRouter.{" "}
        {papel.papel === "visao"
          ? "A visão recebe só o texto, sem anexo."
          : "Usa o mesmo prompt do atendimento."}{" "}
        Nada vai para o cliente e nada é salvo.
      </p>
      <label>
        Mensagem de teste
        <textarea value={texto} onChange={(e) => setTexto(e.target.value)} maxLength={2000} rows={3} />
      </label>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {resultado && (
        <div className="resultado-teste" role="status">
          {resultado.ok ? (
            <>
              {resultado.resposta && <p className="resposta">{resultado.resposta}</p>}
              {resultado.detalhe && (
                <dl>
                  {Object.entries(resultado.detalhe).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd>{typeof v === "number" ? v.toLocaleString("pt-BR") : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          ) : (
            <p className="erro">O modelo falhou ({resultado.erro}).</p>
          )}
          <p className="nota">
            {duracao(resultado.latencia_ms)}
            {resultado.custo_usd !== null && ` · ${dolar(resultado.custo_usd)}`}
            {resultado.tokens_entrada !== null &&
              ` · ${tokens(resultado.tokens_entrada)}+${tokens(resultado.tokens_saida ?? 0)} tokens`}
          </p>
        </div>
      )}
    </Dialogo>
  );
}

// ------------------------------------------------------------------ versões

export function AbaVersoes() {
  const { dados } = useModelos();
  const [versoes, setVersoes] = useState<VersaoAgente[] | null>(null);
  const [erro, setErro] = useState("");
  const [restaurar, setRestaurar] = useState<VersaoAgente | null>(null);

  const carregar = useCallback(() => {
    api
      .versoesAgente()
      .then((v) => {
        setVersoes(v);
        setErro("");
      })
      .catch((e: unknown) => setErro(mensagem(e)));
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(useCallback((aviso) => aviso.tipo === "agente" && carregar(), [carregar]));

  if (!versoes)
    return erro ? (
      <Falha titulo="Não deu para carregar as versões." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );
  if (versoes.length === 0)
    return (
      <Vazio
        titulo="Nenhuma versão salva ainda."
        texto="Valem as variáveis de ambiente. A primeira troca de modelo cria a versão 1."
      />
    );

  const rotuloPapel = (p: string) => dados?.papeis.find((x) => x.papel === p)?.rotulo ?? p;

  return (
    <div className="versoes">
      <ol className="trilha-lista">
        {versoes.map((v, i) => {
          const anterior = versoes[i + 1]?.modelos ?? {};
          const mudou = Object.entries(v.modelos).filter(
            ([p, m]) => anterior[p as PapelModelo] !== m,
          );
          return (
            <li key={v.versao} className="turno">
              <div className="turno-topo">
                <strong>Versão {v.versao}</strong>
                {i === 0 && <span className="selo selo-ia">vigente</span>}
                <time dateTime={v.criada_em}>{dataHora(v.criada_em)}</time>
                {v.autor && <span>{v.autor}</span>}
              </div>
              {v.nota && <p>{v.nota}</p>}
              {v.restaurada_de && <p className="nota">Restaurada da versão {v.restaurada_de}.</p>}
              <ul className="lista-mudancas">
                {(i === versoes.length - 1 ? Object.entries(v.modelos) : mudou).map(([p, m]) => (
                  <li key={p}>
                    <strong>{rotuloPapel(p)}</strong>
                    <span>
                      {i < versoes.length - 1 && (
                        <>
                          <code>{anterior[p as PapelModelo] || "—"}</code> →{" "}
                        </>
                      )}
                      <code>{m || "—"}</code>
                    </span>
                  </li>
                ))}
              </ul>
              {i > 0 && dados?.pode_editar && (
                <button type="button" onClick={() => setRestaurar(v)}>
                  Restaurar esta versão
                </button>
              )}
            </li>
          );
        })}
      </ol>
      {restaurar && dados && (
        <ConfirmarRestaurar
          alvo={restaurar}
          dados={dados}
          fechar={() => setRestaurar(null)}
          feito={() => {
            setRestaurar(null);
            carregar();
          }}
        />
      )}
    </div>
  );
}

function ConfirmarRestaurar({
  alvo,
  dados,
  fechar,
  feito,
}: {
  alvo: VersaoAgente;
  dados: ModelosAgente;
  fechar: () => void;
  feito: () => void;
}) {
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);
  function confirmar() {
    setEnviando(true);
    api
      .restaurarVersao(alvo.versao, dados.vigente?.versao ?? null)
      .then(feito)
      .catch((e: unknown) => setErro(mensagem(e)))
      .finally(() => setEnviando(false));
  }
  return (
    <Dialogo
      titulo={`Restaurar a versão ${alvo.versao}`}
      aoFechar={fechar}
      rodape={
        <>
          <button type="button" onClick={fechar}>
            Voltar
          </button>
          <button type="button" className="principal" onClick={confirmar} disabled={enviando}>
            {enviando ? "Restaurando…" : "Restaurar"}
          </button>
        </>
      }
    >
      <AvisoEmAndamento n={dados.em_andamento} />
      <p>
        Cria a versão {(dados.vigente?.versao ?? 0) + 1} com os modelos da versão {alvo.versao}. O
        histórico não se perde.
      </p>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
    </Dialogo>
  );
}
