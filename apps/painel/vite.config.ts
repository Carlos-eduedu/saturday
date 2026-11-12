import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Em dev o Vite faz o papel do nginx: `/admin` vai para a API, e o painel e a
// API ficam na mesma origem (o cookie é SameSite=Strict). `PAINEL_API` troca a
// API local por outra, ex.: PAINEL_API=https://saturday-dev.dynatech.systems.
export default defineConfig(({ mode }) => {
  const api = loadEnv(mode, ".", "PAINEL_").PAINEL_API || "http://localhost:8000";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/admin": { target: api, changeOrigin: true } },
    },
  };
});
