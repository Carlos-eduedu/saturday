import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  api,
  mensagemDeFalha,
  type Execucao,
  type NoDoGrafo,
  type SituacaoExecucao,
} from "../api";
import { Abas, idAba } from "../componentes/Abas";
import { Falha } from "../componentes/Falha";
import GlideSelect from "../componentes/GlideSelect";
import { ModalGrafo } from "../componentes/Grafo";
import { ItemTurno } from "../componentes/ItemTurno";
import { Vazio } from "../componentes/Vazio";
import { NOS, rotulo } from "../rotulos";
import { useAvisos } from "../tempoReal";
import { AbaConhecimento } from "./AgenteConhecimento";
import { AbaModelos, AbaVersoes } from "./AgenteModelos";

type Aba = "execucoes" | "modelos" | "conhecimento" | "versoes";
const INICIO = "__start__";
const FIM = "__end__";


// Aba Agente: as execuções de todas as conversas, ao vivo (cada uma abre o
// próprio caminho no grafo que roda, lido da estrutura compilada na API); os modelos de cada etapa e as
// versões da configuração (editar exige a permissão "editar o agente").
export function Agente() {
  const [aba, setAba] = useState<Aba>("execucoes");
  // Os nós do grafo, só para o filtro "Passou pelo nó"; sem eles, o filtro
  // fica com "Qualquer" e o modal do grafo mostra o próprio erro.
  const [nos, setNos] = useState<NoDoGrafo[]>([]);
  useEffect(() => {
    api
      .grafo()
      .then((g) => setNos(g.nos.filter((n) => n.id !== INICIO && n.id !== FIM)))
      .catch(() => undefined);
  }, []);

  return (
    <div className="agente">
      <h1 className="titulo-tela">Agente</h1>
      <Abas
        rotulo="Agente"
        opcoes={[
          ["execucoes", "Execuções"],
          ["modelos", "Modelos"],
          ["conhecimento", "Conhecimento"],
          ["versoes", "Versões"],
        ]}
        valor={aba}
        mudar={setAba}
        painel="agente-painel"
      />
      <div role="tabpanel" id="agente-painel" aria-labelledby={idAba("agente-painel", aba)} className="painel-aba">
      {aba === "modelos" && <AbaModelos />}
      {aba === "conhecimento" && <AbaConhecimento />}
      {aba === "versoes" && <AbaVersoes />}
      {aba === "execucoes" && <ListaExecucoes nos={nos} />}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ execuções

function ListaExecucoes({ nos }: { nos: NoDoGrafo[] }) {
  const [filtroNo, setFiltroNo] = useState("");
  // Caminho da execução aberta em "Ver grafo".
  const [grafoAberto, setGrafoAberto] = useState<Execucao | null>(null);
  const [situacao, setSituacao] = useState<SituacaoExecucao>("todas");
  const [lista, setLista] = useState<Execucao[] | null>(null);
  const [temMais, setTemMais] = useState(false);
  const [erro, setErro] = useState("");
  const [carregandoMais, setCarregandoMais] = useState(false);
  // O filtro vigente, para descartar respostas de um filtro que já mudou.
  const chave = `${situacao}|${filtroNo}`;
  const chaveAtual = useRef(chave);
  chaveAtual.current = chave;

  // `reiniciar` troca a lista; sem ele (aviso ao vivo), só entra o que é mais
  // novo e o que já foi paginado fica.
  const primeiraPagina = useCallback((reiniciar = true) => {
    const pedida = `${situacao}|${filtroNo}`;
    api
      .execucoes({ situacao, no: filtroNo || undefined })
      .then((r) => {
        if (chaveAtual.current !== pedida) return;
        setErro("");
        if (reiniciar) {
          setLista(r.execucoes);
          setTemMais(r.tem_mais);
          return;
        }
        setLista((atual) => {
          const topo = atual?.[0]?.id ?? 0;
          return [...r.execucoes.filter((e) => e.id > topo), ...(atual ?? [])];
        });
      })
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, [situacao, filtroNo]);

  useEffect(() => {
    setLista(null);
    primeiraPagina();
  }, [primeiraPagina]);

  useAvisos(
    useCallback(
      (aviso) => {
        if (aviso.tipo === "reconectado") {
          setLista(null);
          primeiraPagina();
        } else if (aviso.tipo === "turno") primeiraPagina(false);
      },
      [primeiraPagina],
    ),
  );

  function maisAntigas() {
    if (!lista?.length) return;
    setCarregandoMais(true);
    const pedida = chave;
    api
      .execucoes({ situacao, no: filtroNo || undefined, antes_de: lista[lista.length - 1].id })
      .then((r) => {
        // Filtro trocado no meio do pedido: a página é da lista anterior.
        if (chaveAtual.current !== pedida) return;
        setLista((atual) => [...(atual ?? []), ...r.execucoes]);
        setTemMais(r.tem_mais);
      })
      .catch((e: unknown) => setErro(mensagemDeFalha(e)))
      .finally(() => setCarregandoMais(false));
  }

  return (
    <div className="execucoes">
      <div className="execucoes-filtros">
        <label>
          Situação
          <GlideSelect
            ariaLabel="Situação"
            value={situacao}
            onChange={(v) => setSituacao(v as SituacaoExecucao)}
            menuWidth={220}
            options={[
              { value: "todas", label: "Todas" },
              { value: "erro", label: "Com erro" },
              { value: "handoff", label: "Passadas para a equipe" },
            ]}
          />
        </label>
        <label>
          Passou pelo nó
          <GlideSelect
            ariaLabel="Passou pelo nó"
            value={filtroNo}
            onChange={setFiltroNo}
            menuWidth={240}
            options={[
              { value: "", label: "Qualquer" },
              ...nos.map((n) => ({ value: n.id, label: rotulo(NOS, n.id) })),
            ]}
          />
        </label>
        <span className="ao-vivo" title="A lista recebe as execuções novas sem recarregar">
          Ao vivo
        </span>
      </div>

      {erro && lista && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {!lista ? (
        erro ? (
          <Falha titulo="Não deu para carregar as execuções." texto={erro} aoTentar={() => primeiraPagina()} />
        ) : (
          <p className="centro">Carregando…</p>
        )
      ) : lista.length === 0 ? (
        <Vazio
          titulo="Nenhuma execução com esse filtro."
          texto="Cada turno da IA aparece aqui assim que termina."
        />
      ) : (
        <ol className="trilha-lista">
          {lista.map((e) => (
            <ItemTurno
              key={e.id}
              t={e}
              topo={
                <>
                  <Link to={`/conversas/${e.conversa_id}`}>{e.telefone ?? e.canal}</Link>
                  {e.membro && <span className="selo-membro">Membro · {e.membro.split(" ")[0]}</span>}
                </>
              }
              verGrafo={() => setGrafoAberto(e)}
            />
          ))}
        </ol>
      )}
      {temMais && lista && lista.length > 0 && (
        <button type="button" onClick={maisAntigas} disabled={carregandoMais}>
          {carregandoMais ? "Carregando…" : "Carregar mais antigas"}
        </button>
      )}
      {grafoAberto && (
        <ModalGrafo
          turno={grafoAberto}
          aoFechar={() => setGrafoAberto(null)}
          verExecucoes={(no) => {
            setFiltroNo(no);
            setGrafoAberto(null);
          }}
        />
      )}
    </div>
  );
}
