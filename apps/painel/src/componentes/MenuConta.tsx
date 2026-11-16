import { useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import type { Eu } from "../api";
import { Avatar } from "./Avatar";

// O ícone do usuário no topo. Abre a conta: o próprio perfil e sair. Fica à
// vista também no celular, ao lado do Menu. Os alertas moram na navegação.
export function MenuConta({ eu, aoSair }: { eu: Eu; aoSair: () => void }) {
  const [aberto, setAberto] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const idPainel = useId();
  const { pathname } = useLocation();

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

  return (
    <div className="menu-conta" ref={raiz}>
      <button
        ref={botao}
        type="button"
        className="menu-conta__botao"
        aria-expanded={aberto}
        aria-controls={idPainel}
        aria-label={`Conta de ${eu.nome}`}
        onClick={() => setAberto((a) => !a)}
      >
        <Avatar nome={eu.nome} foto={eu.foto} />
      </button>
      {aberto && (
        <div id={idPainel} className="menu-conta__painel">
          <p className="menu-conta__quem">
            <strong>{eu.nome}</strong>
            <span>{eu.perfil === "gestor" ? "Gestor" : "Atendente"}</span>
          </p>
          <Link to={`/membros/${eu.id}`} className="menu-conta__item">
            Seu perfil
          </Link>
          <button type="button" className="menu-conta__item" onClick={aoSair}>
            Sair
          </button>
        </div>
      )}
    </div>
  );
}
