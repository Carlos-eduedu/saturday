// AnimatedList, da React Bits (reactbits.dev), portado para TypeScript e
// reduzido ao que a lista de conversas usa: o contorno que desliza entre as
// linhas (ponteiro e foco) e o esmaecido das bordas da rolagem. A entrada das
// linhas é só CSS. O componente não desenha as linhas nem é `listbox`: envolve
// uma <ul> de links, que seguem com seus botões e gestos.
import { type ComponentProps, useLayoutEffect, useRef } from "react";

import "./AnimatedList.css";

const ESMAECIDO = 40; // px de degradê na borda que ainda tem linha para rolar

export function AnimatedList({ className = "", children, ...resto }: ComponentProps<"ul">) {
  const lista = useRef<HTMLUListElement>(null);
  const anel = useRef<HTMLLIElement>(null);
  const alvo = useRef<HTMLElement | null>(null);

  // Põe o contorno na linha alvo; vindo do nada, aparece no lugar, sem deslizar.
  function pousar() {
    const a = anel.current;
    const linha = alvo.current;
    if (!a) return;
    if (!linha?.isConnected) {
      alvo.current = null;
      a.style.opacity = "0";
      return;
    }
    const surgindo = a.style.opacity !== "1";
    if (surgindo) a.style.transition = "none";
    a.style.transform = `translate3d(0, ${linha.offsetTop}px, 0)`;
    a.style.height = `${linha.offsetHeight}px`;
    a.style.opacity = "1";
    // Com o foco do teclado no link da linha, o contorno é o próprio foco.
    a.toggleAttribute("data-foco", linha.querySelector("a:focus-visible") !== null);
    if (surgindo) {
      void a.offsetHeight;
      a.style.transition = "";
    }
  }

  // Quanto de cada borda esmaece: o que ainda há para rolar daquele lado.
  function esmaecer() {
    const ul = lista.current;
    if (!ul) return;
    const resto = ul.scrollHeight - ul.clientHeight - ul.scrollTop;
    ul.style.setProperty("--al-topo", `${Math.min(ESMAECIDO, Math.max(0, ul.scrollTop))}px`);
    ul.style.setProperty("--al-pe", `${Math.min(ESMAECIDO, Math.max(0, resto))}px`);
  }

  useLayoutEffect(() => {
    const ul = lista.current;
    if (!ul) return undefined;
    const mirar = (e: Event) => {
      const linha = e.target instanceof Element ? e.target.closest<HTMLElement>("li:not(.al-anel)") : null;
      if (!linha || !ul.contains(linha)) return;
      alvo.current = linha;
      pousar();
    };
    const soltar = () => {
      // O foco do teclado segura o contorno mesmo com o ponteiro fora.
      const focada = document.activeElement?.closest<HTMLElement>("li:not(.al-anel)") ?? null;
      alvo.current = focada && ul.contains(focada) && ul.matches(":focus-within") ? focada : null;
      pousar();
    };
    const medida = new ResizeObserver(() => {
      esmaecer();
      pousar();
    });
    medida.observe(ul);
    ul.addEventListener("scroll", esmaecer, { passive: true });
    ul.addEventListener("pointerover", mirar);
    ul.addEventListener("focusin", mirar);
    ul.addEventListener("pointerleave", soltar);
    ul.addEventListener("focusout", soltar);
    return () => {
      medida.disconnect();
      ul.removeEventListener("scroll", esmaecer);
      ul.removeEventListener("pointerover", mirar);
      ul.removeEventListener("focusin", mirar);
      ul.removeEventListener("pointerleave", soltar);
      ul.removeEventListener("focusout", soltar);
    };
  }, []);

  // A cada desenho: a linha alvo pode ter mudado de lugar, de altura ou saído.
  useLayoutEffect(() => {
    pousar();
    esmaecer();
  });

  return (
    <ul ref={lista} className={`animated-list ${className}`.trim()} {...resto}>
      {children}
      <li ref={anel} className="al-anel" aria-hidden="true" />
    </ul>
  );
}
