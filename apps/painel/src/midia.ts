import { useSyncExternalStore } from "react";

// Se a janela casa com a media query agora; acompanha girar e redimensionar.
export function useMidia(consulta: string): boolean {
  return useSyncExternalStore(
    (avisar) => {
      const m = window.matchMedia(consulta);
      m.addEventListener("change", avisar);
      return () => m.removeEventListener("change", avisar);
    },
    () => window.matchMedia(consulta).matches,
  );
}
