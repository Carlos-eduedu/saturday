import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes } from "react-router";
import { api, type Cota, type Eu, ErroApi, guardarCsrf } from "./api";
import { Alertas } from "./paginas/Alertas";
import { Conversa } from "./paginas/Conversa";
import { Inbox } from "./paginas/Inbox";
import { Login } from "./paginas/Login";
import { iniciarTempoReal, useAvisos } from "./tempoReal";

export function App() {
  const [eu, setEu] = useState<Eu | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    api
      .eu()
      .then(entrar)
      .catch(() => setEu(null))
      .finally(() => setCarregando(false));
  }, []);

  function entrar(usuario: Eu) {
    guardarCsrf(usuario.csrf);
    setEu(usuario);
  }

  async function sair() {
    await api.sair().catch(() => undefined);
    setEu(null);
  }

  if (carregando) return <p className="centro">Carregando…</p>;
  if (!eu) return <Login aoEntrar={entrar} />;
  return <Logado eu={eu} aoSair={sair} />;
}

function Logado({ eu, aoSair }: { eu: Eu; aoSair: () => void }) {
  useEffect(() => iniciarTempoReal(), []);

  return (
    <div className="app">
      <header className="topo">
        <Link to="/" className="marca">
          Saturday
        </Link>
        <nav>
          <Link to="/">Conversas</Link>
          <Link to="/alertas">Alertas</Link>
        </nav>
        <ContadorCota />
        <span className="quem">
          {eu.email} ({eu.perfil})
        </span>
        <button type="button" onClick={aoSair}>
          Sair
        </button>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Inbox eu={eu} />} />
          <Route path="/conversas/:id" element={<Conversa eu={eu} />} />
          <Route path="/alertas" element={<Alertas />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}

function ContadorCota() {
  const [cota, setCota] = useState<Cota | null>(null);
  const carregar = useCallback(() => {
    api.cota().then(setCota).catch((erro: unknown) => {
      if (erro instanceof ErroApi && erro.status === 401) window.location.reload();
    });
  }, []);
  useEffect(carregar, [carregar]);
  // A cota só muda com consulta à Granatech (Fase 4): basta recarregar ao reconectar.
  useAvisos(useCallback((aviso) => aviso.tipo === "reconectado" && carregar(), [carregar]));

  if (!cota) return null;
  const alerta = cota.mes.usadas >= cota.mes.teto * 0.8;
  return (
    <span className={alerta ? "cota cota-alerta" : "cota"} title="Consultas Granatech">
      Cota: {cota.dia.usadas}/{cota.dia.teto} hoje · {cota.mes.usadas}/{cota.mes.teto} no mês
    </span>
  );
}
