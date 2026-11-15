import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router";
import { api, type Cota, type Eu, ErroApi, guardarCsrf, SESSAO_EXPIRADA } from "./api";
import { ConfirmarProvider } from "./componentes/Confirmar";
import { Falha } from "./componentes/Falha";
import { MenuConta } from "./componentes/MenuConta";
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
  // Menu do celular aberto: a página atrás sai do Tab e do leitor de tela.
  const [menuAberto, setMenuAberto] = useState(false);
  const emConversas = pathname === "/" || pathname.startsWith("/conversas");
  const em = (base: string) => pathname === base || pathname.startsWith(`${base}/`);
  const itens = [
    { label: "Conversas", ariaLabel: "Ir para as conversas", link: "/", ativo: emConversas },
    { label: "Bancos", ariaLabel: "Ir para os bancos", link: "/bancos", ativo: em("/bancos") },
    { label: "Agente", ariaLabel: "Ir para o agente", link: "/agente", ativo: em("/agente") },
    ...(eu.perfil === "gestor"
      ? [
          { label: "Canais", ariaLabel: "Ir para os canais", link: "/canais", ativo: em("/canais") },
          { label: "Membros", ariaLabel: "Ir para os membros", link: "/membros", ativo: em("/membros") },
          {
            label: "Operação",
            ariaLabel: "Ir para a operação",
            link: "/operacao",
            ativo: em("/operacao"),
          },
        ]
      : []),
  ];

  return (
    <div className="app">
      {/* Primeiro item do Tab: pula o topo e a navegação. */}
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <StaggeredMenu
        isFixed
        onMenuOpen={() => setMenuAberto(true)}
        onMenuClose={() => setMenuAberto(false)}
        position="right"
        items={itens}
        displaySocials={false}
        displayItemNumbering={false}
        colors={["var(--superficie-2)"]}
        accentColor="var(--destaque)"
        menuButtonColor="var(--texto)"
        openMenuButtonColor="var(--texto)"
        changeMenuColorOnOpen={false}
        logo={
          <div className="marca-topo">
            <Link to="/" className="marca">
              Saturday
            </Link>
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
            </div>
            <MenuConta eu={eu} aoSair={aoSair} />
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
      <main id="conteudo" tabIndex={-1} inert={menuAberto || undefined}>
        <ConfirmarProvider>
        <Routes>
          <Route path="/" element={<Caixa eu={eu} />} />
          <Route path="/conversas/:id" element={<Caixa eu={eu} />} />
          <Route path="/alertas" element={<Alertas />} />
          <Route path="/bancos" element={<Granatech eu={eu} />} />
          <Route path="/agente" element={<Agente />} />
          {eu.perfil === "gestor" && <Route path="/canais" element={<Canais />} />}
          {eu.perfil === "gestor" && <Route path="/membros" element={<Usuarios eu={eu} />} />}
          {eu.perfil === "gestor" && <Route path="/operacao" element={<Custos />} />}
          {/* Endereços antigos, de antes da barra nova: links salvos continuam valendo. */}
          <Route path="/granatech" element={<Navigate to="/bancos" replace />} />
          <Route path="/usuarios" element={<Navigate to="/membros" replace />} />
          <Route path="/custos" element={<Navigate to="/operacao" replace />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
        </ConfirmarProvider>
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
