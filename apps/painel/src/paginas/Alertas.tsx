import { useState } from "react";
import { Link } from "react-router";
import { type Alerta, api, mensagemDeFalha } from "../api";
import { useConfirmar } from "../componentes/Confirmar";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { useRecurso } from "../useRecurso";
import { formatarHora } from "./Inbox";

const ROTULOS: Record<string, string> = {
  handoff: "Conversa aguardando humano",
  atendente_desativado: "Atendente desativado: conversa voltou para a fila",
  erro_interno: "Erro interno no atendimento",
  envio_falhou: "Mensagem não entregue",
  sem_resposta: "Cliente sem resposta há mais de 10 min",
  cota_80: "Cota da Granatech passou de 80% do mês",
  consulta_parada: "Consulta da Granatech sem resposta há mais de 15 min",
  granatech_evento: "Evento da Granatech pede atenção",
  icred_consulta_parada: "Consulta do iCred sem resposta: a conversa seguiu sem ela",
  instancia_desconectada: "Instância da Evolution desconectada",
  instancia_numero_trocado: "Instância reconectada com outro celular (desconectada)",
  integracao_webhook_falhou: "Aviso de status a uma integração não entregue",
};

export function Alertas() {
  // null = ainda não carregou: a tela não diz "nenhum alerta" antes de saber.
  const {
    dado: alertas,
    falha,
    carregar,
  } = useRecurso("alertas", api.alertas, { recarrega: (aviso) => aviso.tipo !== "mensagem" });
  // Falha de uma ação (resolver); a de carga vem do recurso.
  const [erroDaAcao, setErro] = useState("");
  const erro = erroDaAcao || (falha === null ? "" : mensagemDeFalha(falha, "carregar os alertas"));
  const [resolvendo, setResolvendo] = useState<number | null>(null);

  // Resolver todos: um por um, com a rota de sempre (cada um vai para a
  // auditoria). Falha num não para os outros; o aviso diz quantos ficaram.
  const confirmar = useConfirmar();
  const [emLote, setEmLote] = useState(false);
  async function resolverTodos(lista: Alerta[]) {
    const ok = await confirmar({
      titulo: `Resolver os ${lista.length} alertas abertos?`,
      texto:
        "Cada um sai da lista e fica registrado na auditoria em seu nome. Resolver um alerta não muda a " +
        'conversa: quem está em handoff continua na fila "Aguardando humano".',
      acao: `Resolver ${lista.length} alertas`,
    });
    if (!ok) return;
    setEmLote(true);
    let falhas = 0;
    let primeira: unknown = null;
    for (const a of lista) {
      try {
        await api.resolverAlerta(a.id);
      } catch (e) {
        falhas += 1;
        primeira ??= e;
      }
    }
    setEmLote(false);
    setErro(
      falhas === 0
        ? ""
        : `${falhas} de ${lista.length} alertas ficaram abertos. ${mensagemDeFalha(primeira, "resolver os alertas")}`,
    );
    carregar();
  }

  async function resolver(id: number) {
    if (resolvendo !== null || emLote) return;
    setErro("");
    setResolvendo(id);
    try {
      await api.resolverAlerta(id);
    } catch (e) {
      setErro(
        mensagemDeFalha(e, "resolver o alerta"),
      );
    }
    setResolvendo(null);
    carregar();
  }

  if (!alertas)
    return erro ? (
      <Falha titulo="Não deu para carregar os alertas." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  return (
    <section>
      <div className="alertas-cabeca">
        <h1 className="titulo-tela">
          Alertas <span className="contagem">· {alertas.length}</span>
        </h1>
        {alertas.length > 1 && (
          <button type="button" disabled={resolvendo !== null || emLote} onClick={() => resolverTodos(alertas)}>
            {emLote ? "Resolvendo…" : "Resolver todos"}
          </button>
        )}
      </div>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {alertas.length === 0 ? (
        <Vazio
          titulo="Nenhum alerta aberto."
          texto="Cada handoff novo, envio que falhou ou instância que caiu abre um alerta aqui até alguém resolver. Conversas aguardando humano ficam na fila de Conversas."
        />
      ) : (
        <ul className="alertas">
          {alertas.map((a) => (
            <li key={a.id}>
              <strong>{ROTULOS[a.tipo] ?? a.tipo}</strong>
              {typeof a.detalhe?.instancia === "string" && <span>{a.detalhe.instancia}</span>}
              <time>{formatarHora(a.criado_em)}</time>
              {a.conversa_id && <Link to={`/conversas/${a.conversa_id}`}>Abrir conversa</Link>}
              <button
                type="button"
                disabled={resolvendo !== null || emLote}
                onClick={() => resolver(a.id)}
              >
                {resolvendo === a.id ? "Resolvendo…" : "Resolver"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
