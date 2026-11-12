import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router";
import { api, type Cota, type Eu, ErroApi, guardarCsrf } from "./api";
import { Alertas } from "./paginas/Alertas";
import { Canais } from "./paginas/Canais";
import { Custos } from "./paginas/Custos";
import StaggeredMenu from "./componentes/StaggeredMenu";
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
  const { pathname } = useLocation();
  const emConversas = pathname === "/" || pathname.startsWith("/conversas");
  const itens = [
    { label: "Conversas", ariaLabel: "Ir para as conversas", link: "/", ativo: emConversas },
    {
      label: "Alertas",
      ariaLabel: "Ir para os alertas",
      link: "/alertas",
      ativo: pathname === "/alertas",
    },
    ...(eu.perfil === "gestor"
      ? [
          {
            label: "Canais",
            ariaLabel: "Ir para os canais",
            link: "/canais",
            ativo: pathname === "/canais",
          },
          {
            label: "Custos",
            ariaLabel: "Ir para os custos",
            link: "/custos",
            ativo: pathname === "/custos",
          },
        ]
      : []),
  ];

  return (
    <div className="app">
      <StaggeredMenu
        isFixed
        position="right"
        items={itens}
        displaySocials={false}
        displayItemNumbering
        colors={["var(--superficie-2)", "var(--destaque)"]}
        accentColor="var(--destaque)"
        menuButtonColor="var(--texto)"
        openMenuButtonColor="var(--texto)"
        changeMenuColorOnOpen={false}
        logo={
          <div className="marca-topo">
            <Link to="/" className="marca">
              Saturday
            </Link>
            <SeloAlertas />
          </div>
        }
        rodape={
          <div className="conta">
            <ContadorCota />
            <span className="quem">
              {eu.email} ({eu.perfil})
            </span>
            <button type="button" onClick={aoSair}>
              Sair
            </button>
          </div>
        }
      />
      <main>
        <Routes>
          <Route path="/" element={<Inbox eu={eu} />} />
          <Route path="/conversas/:id" element={<Conversa eu={eu} />} />
          <Route path="/alertas" element={<Alertas />} />
          {eu.perfil === "gestor" && <Route path="/canais" element={<Canais />} />}
          {eu.perfil === "gestor" && <Route path="/custos" element={<Custos />} />}
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}

function ContadorCota() {
  const [cota, setCota] = useState<Cota | null>(null);
  const carregar = useCallback(() => {
    api
      .cota()
      .then(setCota)
      .catch((erro: unknown) => {
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

// Com a navegação dentro do menu, os alertas abertos ficam à vista no topo.
function SeloAlertas() {
  const [total, setTotal] = useState(0);
  const carregar = useCallback(() => {
    api
      .alertas()
      .then((lista) => setTotal(lista.length))
      .catch(() => undefined);
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (aviso) => (aviso.tipo === "alerta" || aviso.tipo === "reconectado") && carregar(),
      [carregar],
    ),
  );

  if (total === 0) return null;
  return (
    <Link to="/alertas" className="selo-alertas">
      {total} {total === 1 ? "alerta" : "alertas"}
    </Link>
  );
}
