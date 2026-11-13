import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { type Alerta, api } from "../api";
import { Falha } from "../componentes/Falha";
import { Vazio } from "../componentes/Vazio";
import { useAvisos } from "../tempoReal";
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
  instancia_desconectada: "Instância da Evolution desconectada",
  instancia_numero_trocado: "Instância reconectada com outro celular (desconectada)",
};

export function Alertas() {
  // null = ainda não carregou: a tela não diz "nenhum alerta" antes de saber.
  const [alertas, setAlertas] = useState<Alerta[] | null>(null);
  const [erro, setErro] = useState("");
  const [resolvendo, setResolvendo] = useState<number | null>(null);
  const carregar = useCallback(() => {
    api
      .alertas()
      .then((lista) => {
        setAlertas(lista);
        setErro("");
      })
      .catch((e: unknown) =>
        setErro(e instanceof Error ? e.message : "Não deu para carregar os alertas."),
      );
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(useCallback((aviso) => aviso.tipo !== "mensagem" && carregar(), [carregar]));

  async function resolver(id: number) {
    if (resolvendo !== null) return;
    setResolvendo(id);
    try {
      await api.resolverAlerta(id);
    } catch (e) {
      setErro(
        e instanceof Error ? `Não deu para resolver: ${e.message}` : "Não deu para resolver.",
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
      <h1 className="titulo-tela">
        Alertas <span className="contagem">· {alertas.length}</span>
      </h1>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {alertas.length === 0 ? (
        <Vazio
          titulo="Nenhum alerta aberto."
          texto="Handoffs, envios que falharam e instâncias que caíram aparecem aqui."
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
                disabled={resolvendo !== null}
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
