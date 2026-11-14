import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { FalhaDeTela } from "./componentes/FalhaDeTela";
// Fontes servidas pelo próprio painel: nada de Google Fonts (dados de clientes na tela).
import "@fontsource-variable/red-hat-display";
import "@fontsource-variable/red-hat-text";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./estilo.css";

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <BrowserRouter>
      <FalhaDeTela>
        <App />
      </FalhaDeTela>
    </BrowserRouter>
  </StrictMode>,
);
