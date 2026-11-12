import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { type Alerta, api } from "../api";
import { Vazio } from "../componentes/Vazio";
import { useAvisos } from "../tempoReal";
import { formatarHora } from "./Inbox";

const ROTULOS: Record<string, string> = {
  handoff: "Conversa aguardando humano",
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
  const [alertas, setAlertas] = useState<Alerta[]>([]);
  const carregar = useCallback(() => {
    api
      .alertas()
      .then(setAlertas)
      .catch(() => undefined);
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(useCallback((aviso) => aviso.tipo !== "mensagem" && carregar(), [carregar]));

  async function resolver(id: number) {
    await api.resolverAlerta(id);
    carregar();
  }

  return (
    <section>
      <h1 className="titulo-tela">
        Alertas <span className="contagem">· {alertas.length}</span>
      </h1>
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
              <button type="button" onClick={() => resolver(a.id)}>
                Resolver
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
