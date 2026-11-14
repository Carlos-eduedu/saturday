import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router";
import { api, type Cota, type Eu, ErroApi, guardarCsrf, SESSAO_EXPIRADA } from "./api";
import { Falha } from "./componentes/Falha";
import { Alertas } from "./paginas/Alertas";
import { Canais } from "./paginas/Canais";
import { Agente } from "./paginas/Agente";
import { Custos } from "./paginas/Custos";
import { Granatech } from "./paginas/Granatech";
import StaggeredMenu from "./componentes/StaggeredMenu";
import { Caixa } from "./paginas/Caixa";
import { Login } from "./paginas/Login";
import { Usuarios } from "./paginas/Usuarios";
import { iniciarTempoReal, useAvisos } from "./tempoReal";

export function App() {
  const [eu, setEu] = useState<Eu | null>(null);
  const [carregando, setCarregando] = useState(true);
  // API fora do ar ao abrir: não é o mesmo que "não logado".
  const [falha, setFalha] = useState("");

  const conferir = useCallback(() => {
    setCarregando(true);
    setFalha("");
    api
      .eu()
      .then(entrar)
      .catch((e: unknown) => {
        setEu(null);
        if (!(e instanceof ErroApi && e.status === 401))
          setFalha(e instanceof Error ? e.message : "Não deu para abrir o painel.");
      })
      .finally(() => setCarregando(false));
  }, []);
  useEffect(conferir, [conferir]);

  // Sessão vencida no meio do uso: volta para o login sem recarregar a página.
  useEffect(() => {
    const expirou = () => {
      guardarCsrf("");
      setEu(null);
    };
    window.addEventListener(SESSAO_EXPIRADA, expirou);
    return () => window.removeEventListener(SESSAO_EXPIRADA, expirou);
  }, []);

  function entrar(usuario: Eu) {
    guardarCsrf(usuario.csrf);
    setEu(usuario);
  }

  async function sair() {
    await api.sair().catch(() => undefined);
    guardarCsrf("");
    setEu(null);
  }

  if (carregando) return <p className="centro">Carregando…</p>;
  if (falha) return <Falha titulo="Não deu para abrir o painel." texto={falha} aoTentar={conferir} />;
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
    {
      label: "Granatech",
      ariaLabel: "Ir para a Granatech",
      link: "/granatech",
      ativo: pathname === "/granatech",
    },
    {
      label: "Agente",
      ariaLabel: "Ir para o agente",
      link: "/agente",
      ativo: pathname === "/agente",
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
            label: "Usuários",
            ariaLabel: "Ir para os usuários",
            link: "/usuarios",
            ativo: pathname === "/usuarios",
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
            {/* Desktop: navegação e conta à vista; o menu animado fica só no celular. */}
            <nav className="nav-topo" aria-label="Principal">
              {itens.map((it) => (
                <Link key={it.link} to={it.link} aria-current={it.ativo ? "page" : undefined}>
                  {it.label}
                </Link>
              ))}
            </nav>
            <div className="conta-topo">
              <ContadorCota />
              <span className="quem">{eu.nome}</span>
              <button type="button" onClick={aoSair}>
                Sair
              </button>
            </div>
          </div>
        }
        rodape={
          <div className="conta">
            <ContadorCota />
            <span className="quem">
              {eu.nome} ({eu.perfil})
            </span>
            <button type="button" onClick={aoSair}>
              Sair
            </button>
          </div>
        }
      />
      <main>
        <Routes>
          <Route path="/" element={<Caixa eu={eu} />} />
          <Route path="/conversas/:id" element={<Caixa eu={eu} />} />
          <Route path="/alertas" element={<Alertas />} />
          <Route path="/granatech" element={<Granatech eu={eu} />} />
          <Route path="/agente" element={<Agente />} />
          {eu.perfil === "gestor" && <Route path="/canais" element={<Canais />} />}
          {eu.perfil === "gestor" && <Route path="/usuarios" element={<Usuarios eu={eu} />} />}
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
    // Sessão vencida já volta ao login pelo `api`; o resto deixa a última cota.
    api
      .cota()
      .then(setCota)
      .catch(() => undefined);
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
