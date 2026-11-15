import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { api, type Eu } from "../api";
import { useAvisos } from "../tempoReal";

const iniciais = (nome: string) =>
  nome
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");

// O ícone do usuário no topo, com a contagem de alertas abertos. Abre a conta:
// alertas e sair. Fica à vista também no celular, ao lado do Menu.
export function MenuConta({ eu, aoSair }: { eu: Eu; aoSair: () => void }) {
  const [aberto, setAberto] = useState(false);
  const [alertas, setAlertas] = useState(0);
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const idPainel = useId();
  const { pathname } = useLocation();

  const carregar = useCallback(() => {
    api
      .alertas()
      .then((lista) => setAlertas(lista.length))
      .catch(() => undefined);
  }, []);
  useEffect(carregar, [carregar]);
  useAvisos(
    useCallback(
      (aviso) => (aviso.tipo === "alerta" || aviso.tipo === "reconectado") && carregar(),
      [carregar],
    ),
  );

  // Navegar fecha; clicar fora ou Esc também (Esc devolve o foco ao botão).
  useEffect(() => setAberto(false), [pathname]);
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: PointerEvent) => {
      if (!raiz.current?.contains(e.target as Node)) setAberto(false);
    };
    const tecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setAberto(false);
      botao.current?.focus();
    };
    document.addEventListener("pointerdown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("pointerdown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto]);

  const textoAlertas = alertas === 1 ? "1 alerta aberto" : `${alertas} alertas abertos`;
  return (
    <div className="menu-conta" ref={raiz}>
      <button
        ref={botao}
        type="button"
        className="menu-conta__botao"
        aria-expanded={aberto}
        aria-controls={idPainel}
        aria-label={`Conta de ${eu.nome}${alertas ? `, ${textoAlertas}` : ""}`}
        onClick={() => setAberto((a) => !a)}
      >
        <span className="menu-conta__avatar" aria-hidden="true">
          {iniciais(eu.nome) || "?"}
        </span>
        {alertas > 0 && (
          <span className="menu-conta__selo" aria-hidden="true">
            {alertas > 99 ? "99+" : alertas}
          </span>
        )}
      </button>
      {aberto && (
        <div id={idPainel} className="menu-conta__painel">
          <p className="menu-conta__quem">
            <strong>{eu.nome}</strong>
            <span>{eu.perfil === "gestor" ? "Gestor" : "Atendente"}</span>
          </p>
          <Link to="/alertas" className="menu-conta__item">
            Alertas
            {alertas > 0 && <span className="menu-conta__contagem">{alertas}</span>}
          </Link>
          <button type="button" className="menu-conta__item" onClick={aoSair}>
            Sair
          </button>
        </div>
      )}
    </div>
  );
}
