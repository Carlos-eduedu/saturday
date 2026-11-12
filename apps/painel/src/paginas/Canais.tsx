import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, type Canais as DadosCanais, ErroApi, type InstanciaEvolution, type Qr } from "../api";

// Tela Canais (decisão 0010), só para gestor: números da Meta para consulta e
// instâncias da Evolution geridas aqui. O QR se renova sozinho até conectar.

const RENOVAR_QR_MS = 5000;

const ROTULO_ESTADO: Record<string, string> = {
  open: "conectada",
  connecting: "aguardando QR",
  close: "desconectada",
  refused: "QR esgotado",
};

function mensagemDe(erro: unknown): string {
  return erro instanceof ErroApi ? erro.message : "falha inesperada";
}

export function Canais() {
  const [canais, setCanais] = useState<DadosCanais | null>(null);
  const [erro, setErro] = useState("");
  const [qrDe, setQrDe] = useState<{ nome: string; qr: Qr } | null>(null);

  const carregar = useCallback(() => {
    api
      .canais()
      .then(setCanais)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, []);
  useEffect(carregar, [carregar]);

  async function agir(acao: () => Promise<unknown>) {
    setErro("");
    try {
      await acao();
    } catch (e) {
      setErro(mensagemDe(e));
    }
    carregar();
  }

  if (!canais) return <p className="centro">{erro || "Carregando…"}</p>;

  return (
    <div className="canais">
      {erro && <p className="erro">{erro}</p>}

      <section>
        <h2>WhatsApp oficial (Meta)</h2>
        <p className="nota">Só leitura: os números da Meta são configurados no Meta Business.</p>
        {canais.meta.length === 0 ? (
          <p className="vazio">Nenhum número configurado.</p>
        ) : (
          <ul>
            {canais.meta.map((m) => (
              <li key={m.phone_number_id}>
                <code>{m.phone_number_id}</code>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2>Evolution (WhatsApp Web)</h2>
        {!canais.evolution.ativo ? (
          <p className="vazio">Canal desligado (SATURDAY_EVOLUTION_ATIVO).</p>
        ) : (
          <>
            {canais.evolution.erro && <p className="erro">{canais.evolution.erro}</p>}
            <TabelaInstancias
              instancias={canais.evolution.instancias}
              agir={agir}
              mostrarQr={(nome, qr) => setQrDe({ nome, qr })}
            />
            <NovaInstancia agir={agir} mostrarQr={(nome, qr) => setQrDe({ nome, qr })} />
          </>
        )}
      </section>

      {qrDe && (
        <PainelQr
          nome={qrDe.nome}
          inicial={qrDe.qr}
          fechar={() => {
            setQrDe(null);
            carregar();
          }}
        />
      )}
    </div>
  );
}

function TabelaInstancias({
  instancias,
  agir,
  mostrarQr,
}: {
  instancias: InstanciaEvolution[];
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mostrarQr: (nome: string, qr: Qr) => void;
}) {
  if (instancias.length === 0) return <p className="vazio">Nenhuma instância.</p>;

  function confirmar(verbo: string, i: InstanciaEvolution): boolean {
    return window.confirm(
      `${verbo} a instância ${i.nome}? ${i.conversas_7_dias} conversa(s) falaram por ela nos ` +
        "últimos 7 dias; as respostas pendentes para elas não serão entregues.",
    );
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Instância</th>
          <th>Estado</th>
          <th>Telefone</th>
          <th>Conversas (7 dias)</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {instancias.map((i) => (
          <tr key={i.nome}>
            <td>{i.nome}</td>
            <td data-rotulo="Estado">{ROTULO_ESTADO[i.estado] ?? i.estado}</td>
            <td data-rotulo="Telefone">{i.telefone}</td>
            <td data-rotulo="Conversas (7 dias)">{i.conversas_7_dias}</td>
            <td className="acoes">
              {i.estado !== "open" && (
                <button
                  type="button"
                  onClick={() =>
                    agir(async () => mostrarQr(i.nome, await api.conectarInstancia(i.nome)))
                  }
                >
                  Reconectar
                </button>
              )}
              {i.estado === "open" && (
                <button
                  type="button"
                  onClick={() =>
                    confirmar("Desconectar", i) && agir(() => api.desconectarInstancia(i.nome))
                  }
                >
                  Desconectar
                </button>
              )}
              <button
                type="button"
                className="perigo"
                onClick={() => confirmar("Apagar", i) && agir(() => api.apagarInstancia(i.nome))}
              >
                Apagar
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NovaInstancia({
  agir,
  mostrarQr,
}: {
  agir: (acao: () => Promise<unknown>) => Promise<void>;
  mostrarQr: (nome: string, qr: Qr) => void;
}) {
  const [nome, setNome] = useState("");

  function criar(evento: FormEvent) {
    evento.preventDefault();
    const escolhido = nome.trim();
    if (!escolhido) return;
    agir(async () => {
      mostrarQr(escolhido, await api.criarInstancia(escolhido));
      setNome("");
    });
  }

  return (
    <form onSubmit={criar} className="nova-instancia">
      <label>
        Nova instância
        <input
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          pattern="[a-z0-9-]{3,32}"
          title="De 3 a 32 letras minúsculas, números ou hífen"
          placeholder="mex-vendas"
        />
      </label>
      <button type="submit">Criar e mostrar QR</button>
    </form>
  );
}

function PainelQr({ nome, inicial, fechar }: { nome: string; inicial: Qr; fechar: () => void }) {
  const [qr, setQr] = useState<Qr>(inicial);
  const [erro, setErro] = useState("");

  useEffect(() => {
    if (qr.estado === "open") return;
    const id = window.setInterval(() => {
      api
        .qrInstancia(nome)
        .then(setQr)
        .catch((e: unknown) => setErro(mensagemDe(e)));
    }, RENOVAR_QR_MS);
    return () => window.clearInterval(id);
  }, [nome, qr.estado]);

  return (
    <section className="qr" aria-live="polite">
      <h2>Conectar {nome}</h2>
      {qr.estado === "open" ? (
        <p>Conectada. O telefone fica fixado nesta instância.</p>
      ) : qr.qr ? (
        <>
          <p>No celular: WhatsApp, Aparelhos conectados, Conectar um aparelho.</p>
          <img src={qr.qr} alt={`QR para conectar a instância ${nome}`} width={264} height={264} />
        </>
      ) : (
        <p className="aviso">QR indisponível. Feche e clique em Reconectar.</p>
      )}
      {erro && <p className="erro">{erro}</p>}
      <button type="button" onClick={fechar}>
        Fechar
      </button>
    </section>
  );
}
