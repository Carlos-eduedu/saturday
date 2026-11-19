import { useEffect, useRef, useState } from "react";
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
  type Mensagem,
  mensagemDeFalha,
  midiaUrl,
  type Trilha,
  type Turno,
  type Usuario,
} from "../api";
import { useConfirmar } from "../componentes/Confirmar";
import { pedidoDeTomada, textoDoAviso, useAvisoDesfazer } from "../componentes/Desfazer";
import { Abas, idAba } from "../componentes/Abas";
import { Compositor } from "../componentes/Compositor";
import { Falha } from "../componentes/Falha";
import { ModalGrafo } from "../componentes/Grafo";
import { ItemTurno } from "../componentes/ItemTurno";
import { Vazio } from "../componentes/Vazio";
import { AnexoDaMensagem } from "../componentes/VisorDeMidia";
import {
  PUBLICOS,
  dolar,
  ETAPAS,
  MOTIVOS_HANDOFF,
  NOS,
  OFERTA_DO_RAMO,
  porcento,
  reais,
  rotulo,
  SITUACAO_CONTRATO_NOVO,
  SITUACAO_DA_OFERTA,
  SITUACAO_DA_PROPOSTA,
  SITUACAO_ICRED,
  TIPO_ICRED,
  TIPOS_DE_PROVA,
  tokens,
} from "../rotulos";
import { ROTULO_ESTADO } from "../membros";
import { permissoesDa } from "../permissoes";
import { useRecurso } from "../useRecurso";
import {
  centavosCitados,
  foraDaOferta,
  ofertaDaFala,
  origemDaMensagem,
  reaisDeCentavos,
} from "./conferencia";
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

// Dado revelado volta a ficar mascarado sozinho depois disto.
const REMASCARAR_MS = 60_000;

type Aba = "mensagens" | "ficha" | "ia";

// Carrega um recurso da conversa e recarrega com os avisos do tempo real.
// Trocar de conversa esconde o que era da anterior; recarregar mantém à vista
// o que já estava (e uma falha ao recarregar também).
function useDaConversa<T>(id: string, buscar: (id: string) => Promise<T>, oQue: string) {
  const { dado, falha, carregar } = useRecurso(id, () => buscar(id), {
    recarrega: (aviso) => aviso.conversa === id,
  });
  return { dado, erro: falha === null ? "" : mensagemDeFalha(falha, oQue), carregar };
}

// Prévia curta para o leitor de tela anunciar a mensagem que chegou.
function previa(m: Mensagem): string {
  const texto = m.conteudo.replace(/\s+/g, " ").trim();
  if (!texto || (m.anexos.length > 0 && ANEXO_SEM_LEGENDA.test(m.conteudo))) return "enviou um anexo";
  return texto.length > 120 ? `${texto.slice(0, 119)}…` : texto;
}

// Teclas soltas só valem fora de campos e de diálogos abertos.
function emCampo(alvo: EventTarget | null): boolean {
  return (
    alvo instanceof HTMLElement &&
    (alvo.isContentEditable || alvo.closest("input, textarea, select, dialog") !== null)
  );
}

// `fichaEmAba`: sem espaço para a coluna lateral (conversa ao lado da lista),
// ficha e trilha da IA viram abas ao lado das mensagens.
export function Conversa({ eu, fichaEmAba = false }: { eu: Eu; fichaEmAba?: boolean }) {
  const { id = "" } = useParams();
  const [aba, setAba] = useState<Aba>("mensagens");
  const carga = useDaConversa(id, api.conversa, "carregar a conversa");
  const conversa = carga.dado;
  // Ficha e trilha sobem até aqui: a fala da IA é conferida com a oferta e o
  // turno que a gerou, e a coluna lateral mostra os mesmos dados.
  const ficha = useDaConversa(id, api.ficha, "carregar a ficha");
  const trilha = useDaConversa(id, api.turnos, "carregar a trilha da IA");
  const [erro, setErro] = useState("");

  async function agir(acao: () => Promise<unknown>) {
    setErro("");
    try {
      await acao();
      carga.carregar();
    } catch (e) {
      setErro(mensagemDeFalha(e));
    }
  }

  // A leitura começa pela última mensagem e a acompanha enquanto a pessoa está
  // no fim. Quem rola é a lista, não a página: cabeçalho e envio ficam parados.
  const lista = useRef<HTMLOListElement | null>(null);
  const noFim = useRef(true);
  function medir() {
    const el = lista.current;
    if (el) noFim.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80;
  }
  const ultima = conversa?.mensagens[conversa.mensagens.length - 1]?.id;
  useEffect(() => {
    const el = lista.current;
    if (el && noFim.current) el.scrollTop = el.scrollHeight;
    // Assumir muda a altura do envio; voltar à aba Mensagens remonta a lista.
  }, [ultima, conversa?.atendimento, aba]);

  // Mensagem nova na conversa aberta vira um aviso educado ao leitor de tela.
  // A primeira carga não anuncia nada, nem o que a própria pessoa enviou.
  const [anuncio, setAnuncio] = useState("");
  const vista = useRef<{ id: string; ultima: number } | null>(null);
  useEffect(() => {
    if (!conversa) return;
    const antes = vista.current;
    vista.current = { id, ultima: ultima ?? 0 };
    if (antes?.id !== id) return;
    const novas = conversa.mensagens.filter((m) => m.id > antes.ultima && m.usuario_id !== eu.id);
    const m = novas[novas.length - 1];
    if (!m) return;
    const mais = novas.length > 1 ? ` (e mais ${novas.length - 1})` : "";
    setAnuncio(`${AUTOR[m.autor]}: ${previa(m)}${mais}`);
  }, [conversa, id, ultima, eu.id]);

  // Quem está com a conversa: para o selo, a transferência e a confirmação de tomada.
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  useEffect(() => {
    api
      .usuarios()
      .then(setUsuarios)
      .catch(() => undefined);
  }, []);
  const avisar = useAvisoDesfazer();
  const confirmar = useConfirmar();
  // Assumir pelo cabeçalho leva o cursor para a mensagem.
  const [focarEnvio, setFocarEnvio] = useState(false);
  // Assumir, devolver e transferir em andamento: o duplo clique não repete.
  const [ocupado, setOcupado] = useState(false);
  function agirUmaVez(acao: () => Promise<unknown>): Promise<void> {
    if (ocupado) return Promise.resolve();
    setOcupado(true);
    return agir(acao).finally(() => setOcupado(false));
  }

  // Atalhos de teclado: "a" assume e "d" devolve, quando a ação está liberada.
  // O ouvinte fica fixo; o que cada tecla faz é atualizado a cada render.
  const atalho = useRef<(tecla: string) => boolean>(() => false);
  useEffect(() => {
    const ouvir = (e: globalThis.KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat || emCampo(e.target)) return;
      if (document.querySelector("dialog[open]")) return;
      if (atalho.current(e.key.toLowerCase())) e.preventDefault();
    };
    document.addEventListener("keydown", ouvir);
    return () => document.removeEventListener("keydown", ouvir);
  }, []);

  if (!conversa) {
    atalho.current = () => false;
    return carga.erro ? (
      <Falha titulo="Não deu para abrir a conversa." texto={carga.erro} aoTentar={carga.carregar} />
    ) : (
      <EsqueletoConversa fichaEmAba={fichaEmAba} />
    );
  }
  const { minha, podeAssumir, tomaDeOutro, podeDevolver, podeMexer } = permissoesDa(conversa, eu);
  const dono = usuarios.find((u) => u.id === conversa.atendente_id)?.nome ?? "outra pessoa";
  const temEnvio = conversa.envia;

  // Assumir e devolver valem na hora; o aviso deixa desfazer por 5 s.
  async function mudar(acao: "assumir" | "devolver") {
    if (acao === "assumir" && tomaDeOutro && !(await confirmar(pedidoDeTomada(dono))))
      return;
    setFocarEnvio(acao === "assumir");
    void agirUmaVez(async () => {
      await (acao === "assumir" ? api.assumir(id) : api.devolver(id));
      avisar({
        id,
        texto: textoDoAviso(acao, conversa?.telefone ?? conversa?.canal ?? ""),
        depois: carga.carregar,
      });
    });
  }
  atalho.current = (tecla) => {
    if (ocupado) return false;
    if (tecla === "a" && podeAssumir) void mudar("assumir");
    else if (tecla === "d" && podeDevolver) void mudar("devolver");
    else return false;
    return true;
  };

  const turnos = trilha.dado?.turnos;

  return (
    <div className={fichaEmAba ? "conversa em-abas" : "conversa"}>
      <section className="historico">
        {/* Só esconde Assumir/Devolver do cabeçalho (celular) quando o envio, que
            os repete, está à mostra: nas abas Ficha e IA ele não aparece. */}
        <header className={temEnvio && (!fichaEmAba || aba === "mensagens") ? "tem-envio" : undefined}>
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
              {conversa.membro && (
                <span className="selo-membro" title="Conversa de teste: telefone de um membro com a permissão testar fluxos">
                  Membro · {conversa.membro}
                </span>
              )}
              <span className="contexto">
                {conversa.canal === "evolution" ? "Evolution" : "WhatsApp oficial"}
              </span>
              {conversa.etapa && <span className="contexto">{rotulo(ETAPAS, conversa.etapa)}</span>}
              {/* Janela aberta é o normal: só a fechada muda o que dá para enviar. */}
              {conversa.janela === "fechada" && (
                <span className="janela fechada">janela fechada</span>
              )}
              {conversa.aguardando_desde && (
                <span className="espera">{textoDaEspera(conversa, Date.now())}</span>
              )}
              {conversa.motivo_handoff && (
                <span className="motivo">{rotulo(MOTIVOS_HANDOFF, conversa.motivo_handoff)}</span>
              )}
            </p>
          </div>
          <Acoes
            conversa={conversa}
            usuarios={usuarios}
            podeAssumir={podeAssumir}
            podeDevolver={podeDevolver}
            podeMexer={podeMexer}
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
        <p className="sr" aria-live="polite">
          {anuncio}
        </p>
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
            painel="conversa-painel"
          />
        )}
        {fichaEmAba && aba === "ficha" && (
          <div role="tabpanel" id="conversa-painel" aria-labelledby={idAba("conversa-painel", aba)}>
            <FichaCliente key={id} id={id} ficha={ficha.dado} erro={ficha.erro} carregar={ficha.carregar} />
          </div>
        )}
        {fichaEmAba && aba === "ia" && (
          <div role="tabpanel" id="conversa-painel" aria-labelledby={idAba("conversa-painel", aba)}>
            <TrilhaIa trilha={trilha.dado} erro={trilha.erro} carregar={trilha.carregar} />
          </div>
        )}
        {(!fichaEmAba || aba === "mensagens") && (
          // Sem abas, as mensagens são só a coluna principal, não um painel de aba.
          <div
            className="painel-mensagens"
            role={fichaEmAba ? "tabpanel" : undefined}
            id={fichaEmAba ? "conversa-painel" : undefined}
            aria-labelledby={fichaEmAba ? idAba("conversa-painel", aba) : undefined}
          >
            {conversa.mensagens.length === 0 && (
              <Vazio
                titulo="Nenhuma mensagem nesta conversa."
                texto="As falas do cliente, da IA e da equipe aparecem aqui assim que chegam."
              />
            )}
            <ol className="mensagens" ref={lista} onScroll={medir}>
              {conversa.mensagens.map((m) => (
                <li key={m.id} className={`msg msg-${m.direcao} msg-${m.autor}`}>
                  <span className="autor">{AUTOR[m.autor]}</span>
                  {/* Anexo sem legenda grava "[documento nome]": o anexo já se mostra. */}
                  {!(m.anexos.length > 0 && ANEXO_SEM_LEGENDA.test(m.conteudo)) && <p>{m.conteudo}</p>}
                  {m.anexos.map((anexo, indice) => {
                    const url = midiaUrl(m.id, indice);
                    if (anexo.mime_type.startsWith("audio/"))
                      return <audio key={indice} className="anexo-audio" controls preload="none" src={url} />;
                    return <AnexoDaMensagem key={indice} url={url} mime={anexo.mime_type} nome={anexo.nome} />;
                  })}
                  {m.autor === "ia" && turnos && (
                    <Conferencia m={m} turnos={turnos} ficha={ficha.dado} />
                  )}
                  <small>
                    <time dateTime={m.criada_em}>{formatarHora(m.criada_em)}</time>
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
            {temEnvio && (
              <Compositor
                conversa={conversa}
                eu={eu}
                minha={minha}
                focar={focarEnvio}
                assumir={podeAssumir ? { acao: () => mudar("assumir"), ocupado } : undefined}
                devolver={podeDevolver ? { acao: () => mudar("devolver"), ocupado } : undefined}
                agir={(acao) => {
                  // Quem envia quer ver a própria mensagem, mesmo lendo mais acima.
                  noFim.current = true;
                  return agir(acao);
                }}
              />
            )}
            {conversa.instancia_apagada && (
              <div className="envio">
                <p className="aviso" role="status">
                  A instância desta conversa foi apagada: a resposta só sai quando o cliente escrever
                  para um número conectado.
                </p>
              </div>
            )}
          </div>
        )}
      </section>
      {!fichaEmAba && (
        <Lateral id={id} ficha={ficha} trilha={trilha} />
      )}
    </div>
  );
}

// Enquanto a conversa chega: balões no lugar das mensagens, sem texto solto.
function EsqueletoConversa({ fichaEmAba }: { fichaEmAba: boolean }) {
  return (
    <div className={fichaEmAba ? "conversa em-abas" : "conversa"}>
      <section className="historico" aria-busy="true">
        <p className="sr" role="status">
          Carregando a conversa…
        </p>
        <div className="esqueleto-topo" aria-hidden="true" />
        <ol className="mensagens" aria-hidden="true">
          {(["entrada", "saida", "entrada", "saida", "entrada"] as const).map((direcao, i) => (
            <li key={i} className={`msg msg-${direcao} esqueleto-msg`} />
          ))}
        </ol>
      </section>
      {!fichaEmAba && (
        <aside className="lateral" aria-hidden="true">
          <div className="esqueleto-blocos">
            <span />
            <span />
          </div>
        </aside>
      )}
    </div>
  );
}

function EsqueletoBlocos({ rotulo: texto }: { rotulo: string }) {
  return (
    <div className="esqueleto-blocos" aria-busy="true">
      <p className="sr" role="status">
        {texto}
      </p>
      <span aria-hidden="true" />
      <span aria-hidden="true" />
      <span aria-hidden="true" />
    </div>
  );
}

// De onde veio a fala da IA que cita reais e se os valores batem com a oferta
// vigente. Valores são do código (AGENTS.md, regra 2): fala do modelo com
// reais, ou valor fora da oferta, pede conferência.
function Conferencia({ m, turnos, ficha }: { m: Mensagem; turnos: Turno[]; ficha: Ficha | null }) {
  const oferta = ofertaDaFala(m, ficha);
  const qual = oferta ? rotulo(OFERTA_DO_RAMO, oferta.ramo) : "";
  const proposta = ficha?.proposta;
  const citados = centavosCitados(m.conteudo);
  if (citados.length === 0) return null;
  const origem = origemDaMensagem(m, turnos);
  const fora = foraDaOferta(citados, oferta);
  const turno = origem.tipo === "sem-registro" ? undefined : origem.turno;
  const nos = turno ? turno.caminho.filter((n) => !n.startsWith("__")) : [];
  const caminho = nos.map((n) => rotulo(NOS, n)).join(" → ");
  return (
    <p className="conferencia">
      {origem.tipo === "fixa" && <span title={caminho}>Mensagem fixa · {origem.chave}</span>}
      {origem.tipo === "codigo" && (
        <span title={caminho}>Código · {rotulo(NOS, nos[nos.length - 1] ?? "")}</span>
      )}
      {origem.tipo === "modelo" && (
        <strong className="atencao" title={caminho}>
          {origem.exato ? "Modelo (FAQ)" : "Turno com o modelo (FAQ)"}
        </strong>
      )}
      {/* Sem turno gravado não dá para dizer de onde o valor saiu: pede conferência. */}
      {origem.tipo === "sem-registro" && (
        <strong className="atencao">Valor sem origem registrada: confira</strong>
      )}
      {fora === null ? (
        <span>
          sem oferta vigente para comparar
          {proposta && ` · proposta: ${proposta.numero_parcelas} × ${reais(proposta.valor_parcela)}`}
        </span>
      ) : fora.length > 0 ? (
        <strong className="atencao difere">
          Difere da {qual}: {fora.map(reaisDeCentavos).join(", ")}
        </strong>
      ) : (
        <span>confere com a {qual}</span>
      )}
    </p>
  );
}

function Acoes({
  conversa,
  usuarios,
  podeAssumir,
  podeDevolver,
  podeMexer,
  agir,
  mudar,
  ocupado,
}: {
  conversa: Detalhe;
  usuarios: Usuario[];
  podeAssumir: boolean;
  podeDevolver: boolean;
  podeMexer: boolean;
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mudar: (acao: "assumir" | "devolver") => void;
  ocupado: boolean;
}) {
  const [destino, setDestino] = useState("");

  return (
    <div className="acoes">
      {/* No celular, Assumir e Devolver ficam no envio, perto do polegar. */}
      {podeAssumir && (
        <button
          type="button"
          className="acao-primaria"
          disabled={ocupado}
          onClick={() => mudar("assumir")}
          title="Assumir (tecla A)"
          aria-keyshortcuts="A"
        >
          Assumir
        </button>
      )}
      {podeDevolver && (
        <button
          type="button"
          className="acao-primaria acao-devolver"
          disabled={ocupado}
          onClick={() => mudar("devolver")}
          title="Devolver para a IA (tecla D)"
          aria-keyshortcuts="D"
        >
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
          {/* No celular o cabeçalho é uma linha só: canal e etapa vêm para cá. */}
          <p className="mais-contexto">
            {conversa.canal === "evolution" ? "Evolution" : "WhatsApp oficial"}
            {conversa.etapa && ` · ${rotulo(ETAPAS, conversa.etapa)}`}
          </p>
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
                        {/* Informação, não bloqueio: dá para transferir a quem está ausente. */}
                        {u.estado !== "disponivel" && ` (${ROTULO_ESTADO[u.estado].toLowerCase()})`}
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
          {/* No celular o cabeçalho não tem Devolver: fica aqui e, para o dono, também no envio. */}
          {podeDevolver && (
            <button type="button" className="mais-celular" disabled={ocupado} onClick={() => mudar("devolver")}>
              Devolver para a IA
            </button>
          )}
          <a className="botao" href={exportarUrl(conversa.id)}>
            Exportar conversa (.md)
          </a>
        </div>
      </details>
    </div>
  );
}

type Recurso<T> = { dado: T | null; erro: string; carregar: () => void };

// Coluna da direita: a Ficha do cliente ou a trilha da IA, turno a turno.
function Lateral({ id, ficha, trilha }: { id: string; ficha: Recurso<Ficha>; trilha: Recurso<Trilha> }) {
  const [aba, setAba] = useState<"ficha" | "ia">("ficha");
  // Trocar de aba volta ao topo: a rolagem da outra aba não vale para esta.
  const coluna = useRef<HTMLElement>(null);
  const trocarAba = (nova: "ficha" | "ia") => {
    setAba(nova);
    coluna.current?.scrollTo({ top: 0 });
  };
  return (
    <aside ref={coluna} className="lateral">
      <Abas
        rotulo="Painel lateral"
        opcoes={[
          ["ficha", "Ficha"],
          ["ia", "IA"],
        ]}
        valor={aba}
        mudar={trocarAba}
        painel="lateral-painel"
      />
      <div role="tabpanel" id="lateral-painel" aria-labelledby={idAba("lateral-painel", aba)}>
        {aba === "ficha" ? (
          <FichaCliente key={id} id={id} ficha={ficha.dado} erro={ficha.erro} carregar={ficha.carregar} />
        ) : (
          <TrilhaIa trilha={trilha.dado} erro={trilha.erro} carregar={trilha.carregar} />
        )}
      </div>
    </aside>
  );
}

function TrilhaIa({ trilha, erro, carregar }: { trilha: Trilha | null; erro: string; carregar: () => void }) {
  // Caminho do turno aberto em "Ver grafo".
  const [grafoAberto, setGrafoAberto] = useState<Turno | null>(null);
  // Falhar ao recarregar mantém a última trilha à vista.
  if (!trilha)
    return erro ? (
      <Falha titulo="Não deu para carregar a trilha da IA." texto={erro} aoTentar={carregar} />
    ) : (
      <EsqueletoBlocos rotulo="Carregando a trilha da IA…" />
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
          <ItemTurno key={t.id} t={t} verGrafo={() => setGrafoAberto(t)} />
        ))}
      </ol>
      {grafoAberto && <ModalGrafo turno={grafoAberto} aoFechar={() => setGrafoAberto(null)} />}
    </div>
  );
}

// `key={id}` em quem usa: trocar de conversa remonta e volta a mascarar tudo.
function FichaCliente({
  id,
  ficha,
  erro: erroCarga,
  carregar,
}: {
  id: string;
  ficha: Ficha | null;
  erro: string;
  carregar: () => void;
}) {
  const [revelados, setRevelados] = useState<Partial<Record<CampoSensivel, string>>>({});
  // O dado revelado não fica à vista o turno todo: volta a ser mascarado sozinho.
  useEffect(() => {
    if (Object.keys(revelados).length === 0) return;
    const timer = window.setTimeout(() => setRevelados({}), REMASCARAR_MS);
    return () => window.clearTimeout(timer);
  }, [revelados]);
  function ocultar(campo: CampoSensivel) {
    setRevelados((atual) => {
      const resto = { ...atual };
      delete resto[campo];
      return resto;
    });
  }

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
        mensagemDeFalha(e, "revelar o dado"),
      );
    }
    setRevelando(null);
  }

  // Falhar ao recarregar mantém a última ficha: some só o que nunca chegou.
  if (!ficha)
    return erroCarga ? (
      <Falha titulo="Não deu para carregar a ficha." texto={erroCarga} aoTentar={carregar} />
    ) : (
      <EsqueletoBlocos rotulo="Carregando a ficha…" />
    );
  return (
    <>
      <Acompanhamento ficha={ficha} />
      <div className="ficha">
        <h2>Dados do cliente</h2>
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
                  {revelados[campo] ? (
                    <button
                      type="button"
                      className="link alvo"
                      onClick={() => ocultar(campo)}
                      aria-label={`Ocultar ${CAMPOS[campo]}`}
                    >
                      Ocultar
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="link alvo"
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
          Revelar um dado fica registrado na auditoria, em seu nome, e ele volta a ser mascarado em
          1 minuto.
        </p>
      </div>
    </>
  );
}

// O que a IA disse em valores, ao lado da fala: contrato novo do C6, consulta
// no iCred, portabilidade, oferta do CLT, proposta no banco e as provas do
// SIM. Só aparece quando a jornada chegou a algum deles. A seção da última
// oferta mostrada ao cliente leva a marca "oferta vigente"; a da oferta que o
// cliente recusou, "recusada". Quem decide a situação é o servidor.
function Acompanhamento({ ficha }: { ficha: Ficha }) {
  const { oferta, proposta, consentimentos, icred, contrato_novo: novo } = ficha;
  const { portabilidade_oferta: portabilidade, ofertas } = ficha;
  if (!oferta && !proposta && !icred && !novo && !portabilidade && consentimentos.length === 0)
    return null;
  const marca = (ramo: string) => {
    const situacao = ofertas[ramo]?.situacao;
    return situacao && <span className="nota"> · {rotulo(SITUACAO_DA_OFERTA, situacao)}</span>;
  };
  return (
    <div className="ficha">
      {novo && (
        <>
          <h2>Contrato novo no C6{marca("contrato_novo")}</h2>
          <dl>
            <div>
              <dt>Situação</dt>
              <dd className="texto">{rotulo(SITUACAO_CONTRATO_NOVO, novo.situacao)}</dd>
            </div>
            <div>
              <dt>Valor na conta</dt>
              <dd>{reais(novo.valor)}</dd>
            </div>
            <div>
              <dt>Parcelas</dt>
              <dd>
                {novo.numero_parcelas} × {reais(novo.valor_parcela)}
              </dd>
            </div>
            <div>
              <dt>Taxa</dt>
              <dd>{porcento(novo.taxa_mensal)}</dd>
            </div>
            {/* Códigos do banco, crus: o manual do C6 não dá nome a eles. */}
            <div>
              <dt>Convênio (código)</dt>
              <dd>{novo.convenio}</dd>
            </div>
            <div>
              <dt>Produto (código)</dt>
              <dd>{novo.produto}</dd>
            </div>
          </dl>
        </>
      )}
      {icred && (
        <>
          <h2>Consulta no iCred{marca("icred")}</h2>
          <dl>
            <div>
              <dt>Situação</dt>
              <dd className="texto">
                {icred.situacao ? rotulo(SITUACAO_ICRED, icred.situacao) : "Aguardando o resultado"}
              </dd>
            </div>
            {icred.contratos.map((c, i) => (
              <div key={i}>
                <dt>{rotulo(TIPO_ICRED, c.tipo)}</dt>
                <dd>
                  {reais(c.liberado)} na conta · {c.prazo} × {reais(c.parcela)} · {porcento(c.taxa)}
                </dd>
              </div>
            ))}
            {icred.contratos.length > 1 && (
              <div>
                <dt>Total na conta</dt>
                <dd>{reais(icred.contratos.reduce((soma, c) => soma + Number(c.liberado), 0))}</dd>
              </div>
            )}
          </dl>
          {icred.valido_ate && new Date(icred.valido_ate).getTime() < Date.now() && (
            <p className="faixa-atencao">
              <strong>Consulta vencida.</strong> Consulte de novo no iCred antes de gravar a proposta.
            </p>
          )}
        </>
      )}
      {portabilidade && (
        <>
          <h2>Portabilidade no C6{marca("portabilidade")}</h2>
          <dl>
            <div>
              <dt>Sobra aproximada</dt>
              <dd>
                {reais(portabilidade.minimo)} a {reais(portabilidade.maximo)}
              </dd>
            </div>
            {portabilidade.contratos.map((c, i) => (
              <div key={i}>
                <dt>{c.banco ?? "Contrato"}</dt>
                <dd>
                  {reais(c.minimo)} a {reais(c.maximo)}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}
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
                {proposta.status ? rotulo(SITUACAO_DA_PROPOSTA, proposta.status) : "Ainda sem status"}
              </dd>
            </div>
            <div>
              <dt>Parcelas</dt>
              <dd>
                {proposta.numero_parcelas} × {reais(proposta.valor_parcela)}
              </dd>
            </div>
            {proposta.condicoes && (
              <>
                <div>
                  <dt>Liberado</dt>
                  <dd>{reais(proposta.condicoes.liberado)}</dd>
                </div>
                <div>
                  <dt>Taxa e CET</dt>
                  <dd>
                    {porcento(proposta.condicoes.taxa_mensal)} · CET {porcento(proposta.condicoes.cet_mensal)}
                  </dd>
                </div>
                <div>
                  <dt>Seguro</dt>
                  <dd>
                    {proposta.condicoes.seguro_aplicado ? reais(proposta.condicoes.valor_seguro) : "Sem seguro"}
                  </dd>
                </div>
              </>
            )}
          </dl>
          {proposta.difere_da_oferta && (
            <p className="faixa-atencao">
              <strong>Difere da oferta vigente.</strong> Confira qual valor a IA passou ao cliente.
            </p>
          )}
          <p className="nota">
            <Link to="/bancos/granatech">Ver na Granatech</Link>
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
