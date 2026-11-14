import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  type BaseConhecimento,
  enviarFonte,
  ErroApi,
  type FonteConhecimento,
} from "../api";
import { Dialogo } from "../componentes/Dialogo";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { useAvisos } from "../tempoReal";

const mensagem = (e: unknown) => (e instanceof ErroApi ? e.message : "falha ao carregar");
const dataHora = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const MB = 1024 * 1024;
const MAX_ARQUIVO = 10 * MB;
const tamanho = (b: number) =>
  b >= MB ? `${(b / MB).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB` : `${Math.ceil(b / 1024)} KB`;

const STATUS: Record<FonteConhecimento["status"], string> = {
  pendente: "Na fila",
  indexando: "Indexando…",
  pronta: "Pronta",
  erro: "Erro",
};
const TIPO: Record<FonteConhecimento["tipo"], string> = {
  texto: "Texto",
  pdf: "PDF",
  markdown: "Markdown",
  txt: "TXT",
};

// Aba Agente → Conhecimento: fontes que o nó de respostas consulta junto da FAQ.
export function AbaConhecimento() {
  const [base, setBase] = useState<BaseConhecimento | null>(null);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [editando, setEditando] = useState<FonteConhecimento | null>(null);
  const [removendo, setRemovendo] = useState<FonteConhecimento | null>(null);

  const carregar = useCallback(() => {
    api
      .conhecimento()
      .then((b) => {
        setBase(b);
        setErro("");
      })
      .catch((e: unknown) => setErro(mensagem(e)));
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (a) => (a.tipo === "agente" || a.tipo === "reconectado") && carregar(),
      [carregar],
    ),
  );

  function agir(acao: () => Promise<unknown>, feito: string) {
    setAviso("");
    acao()
      .then(() => {
        setAviso(feito);
        carregar();
      })
      .catch((e: unknown) => setAviso(`Não deu: ${mensagem(e)}`));
  }

  if (!base)
    return erro ? (
      <Falha titulo="Não deu para carregar a base de conhecimento." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  const desatualizadas = base.fontes.filter((f) => f.desatualizada).length;

  return (
    <div className="conhecimento">
      <section className="faixa-versao">
        <p>
          Embeddings: <code>{base.modelo_embeddings || "não configurado"}</code>. Para cada dúvida,
          até 4 trechos parecidos entram no prompt junto da FAQ fixa; a IA continua respondendo só
          com o que está escrito.
        </p>
        {desatualizadas > 0 && (
          <p className="aviso-mudanca" role="note">
            {desatualizadas} {desatualizadas === 1 ? "fonte foi indexada" : "fontes foram indexadas"}{" "}
            com outro modelo e não {desatualizadas === 1 ? "entra" : "entram"} na busca até reindexar.
          </p>
        )}
        {base.pode_editar && base.fontes.length > 0 && (
          <button
            type="button"
            onClick={() => agir(() => api.reindexarTodas(), "Todas as fontes voltaram para a fila.")}
          >
            Reindexar todas
          </button>
        )}
        {!base.pode_editar && (
          <p className="nota">Só quem tem a permissão “editar o agente” muda as fontes.</p>
        )}
        {aviso && (
          <p className="nota" role="status">
            {aviso}
          </p>
        )}
      </section>

      {base.pode_editar && <NovaFonte criada={carregar} />}

      {base.fontes.length === 0 ? (
        <Vazio
          titulo="Nenhuma fonte ainda."
          texto="Sem fontes, a IA responde só pela FAQ fixa, como antes."
        />
      ) : (
        <ul className="fontes">
          {base.fontes.map((f) => (
            <li key={f.id} className={`fonte fonte-${f.status}`}>
              <div className="fonte-topo">
                <strong>{f.titulo}</strong>
                <span className="selo">{TIPO[f.tipo]}</span>
                <span className={`status-fonte ${f.status}`}>
                  {STATUS[f.status]}
                  {f.desatualizada && " · modelo antigo"}
                </span>
              </div>
              {f.erro && <p className="erro">{f.erro}</p>}
              <p className="nota">
                {f.arquivo_nome && `${f.arquivo_nome} · `}
                {tamanho(f.tamanho)}
                {f.status === "pronta" && ` · ${f.trechos} ${f.trechos === 1 ? "trecho" : "trechos"}`}
                {" · "}atualizada em {dataHora(f.atualizada_em)}
                {f.autor && ` por ${f.autor}`}
                {f.indexada_em && ` · indexada em ${dataHora(f.indexada_em)}`}
              </p>
              {base.pode_editar && (
                <div className="fonte-acoes">
                  <button type="button" onClick={() => setEditando(f)}>
                    Editar
                  </button>
                  <button
                    type="button"
                    disabled={f.status === "pendente" || f.status === "indexando"}
                    onClick={() =>
                      agir(() => api.reindexarFonte(f.id), `“${f.titulo}” voltou para a fila.`)
                    }
                  >
                    Reindexar
                  </button>
                  <button type="button" className="perigo" onClick={() => setRemovendo(f)}>
                    Remover
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {editando && (
        <EditarFonte
          fonte={editando}
          fechar={() => setEditando(null)}
          salvo={() => {
            setEditando(null);
            carregar();
          }}
        />
      )}
      {removendo && (
        <Dialogo
          titulo={`Remover “${removendo.titulo}”`}
          aoFechar={() => setRemovendo(null)}
          rodape={
            <>
              <button type="button" onClick={() => setRemovendo(null)}>
                Voltar
              </button>
              <button
                type="button"
                className="perigo"
                onClick={() => {
                  const alvo = removendo;
                  setRemovendo(null);
                  agir(() => api.removerFonte(alvo.id), `“${alvo.titulo}” foi removida.`);
                }}
              >
                Remover
              </button>
            </>
          }
        >
          <p className="aviso-mudanca" role="note">
            <strong>Sai da busca na hora.</strong> Os trechos e o arquivo são apagados; não
            há como desfazer.
          </p>
        </Dialogo>
      )}
    </div>
  );
}

function NovaFonte({ criada }: { criada: () => void }) {
  const [modo, setModo] = useState<"texto" | "arquivo">("texto");
  const [titulo, setTitulo] = useState("");
  const [texto, setTexto] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro("");
    if (modo === "arquivo") {
      if (!arquivo) return setErro("Escolha um arquivo.");
      if (arquivo.size > MAX_ARQUIVO) return setErro("O arquivo passa de 10 MB.");
    }
    setEnviando(true);
    const pedido =
      modo === "texto" ? api.adicionarTexto(titulo, texto) : enviarFonte(arquivo as File, titulo);
    pedido
      .then(() => {
        setTitulo("");
        setTexto("");
        setArquivo(null);
        criada();
      })
      .catch((e: unknown) => setErro(mensagem(e)))
      .finally(() => setEnviando(false));
  }

  return (
    <form className="faixa-versao nova-fonte" onSubmit={enviar}>
      <h2>Nova fonte</h2>
      <div className="escolha" role="radiogroup" aria-label="Tipo da fonte">
        {(
          [
            ["texto", "Digitar texto"],
            ["arquivo", "Enviar PDF, Markdown ou TXT"],
          ] as const
        ).map(([v, rotulo]) => (
          <label key={v} className="opcao">
            <input type="radio" name="modo" checked={modo === v} onChange={() => setModo(v)} />
            {rotulo}
          </label>
        ))}
      </div>
      <label>
        Título
        <input value={titulo} onChange={(e) => setTitulo(e.target.value)} maxLength={120} required />
      </label>
      {modo === "texto" ? (
        <label>
          Texto
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            rows={6}
            maxLength={200000}
            required
          />
        </label>
      ) : (
        <label>
          Arquivo (até 10 MB; PDF precisa de texto selecionável)
          <input
            type="file"
            accept=".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
            onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
            required
          />
        </label>
      )}
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      <button type="submit" disabled={enviando}>
        {enviando ? "Enviando…" : "Adicionar e indexar"}
      </button>
    </form>
  );
}

function EditarFonte({
  fonte,
  fechar,
  salvo,
}: {
  fonte: FonteConhecimento;
  fechar: () => void;
  salvo: () => void;
}) {
  const [titulo, setTitulo] = useState(fonte.titulo);
  const [texto, setTexto] = useState<string | null>(null);
  const [erro, setErro] = useState("");

  function salvar() {
    const dados: { titulo?: string; texto?: string } = {};
    if (titulo.trim() !== fonte.titulo) dados.titulo = titulo;
    if (texto !== null) dados.texto = texto;
    api
      .editarFonte(fonte.id, dados)
      .then(salvo)
      .catch((e: unknown) => setErro(mensagem(e)));
  }

  return (
    <Dialogo
      titulo={`Editar “${fonte.titulo}”`}
      aoFechar={fechar}
      rodape={
        <>
          <button type="button" onClick={fechar}>
            Voltar
          </button>
          <button type="button" className="principal" onClick={salvar}>
            Salvar
          </button>
        </>
      }
    >
      <label>
        Título
        <input value={titulo} onChange={(e) => setTitulo(e.target.value)} maxLength={120} />
      </label>
      {fonte.editavel ? (
        <label>
          Novo texto (deixe em branco para manter o atual)
          <textarea
            value={texto ?? ""}
            onChange={(e) => setTexto(e.target.value || null)}
            rows={8}
            maxLength={200000}
          />
        </label>
      ) : (
        <p className="nota">O conteúdo de um arquivo não se edita: remova e envie outro.</p>
      )}
      {texto !== null && (
        <p className="aviso-mudanca" role="note">
          O texto novo é reindexado; até terminar, esta fonte sai da busca.
        </p>
      )}
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
    </Dialogo>
  );
}
