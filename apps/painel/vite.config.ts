import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Em dev o Vite faz o papel do nginx: `/admin` vai para a API local, e o
// painel e a API ficam na mesma origem (o cookie é SameSite=Strict).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/admin": "http://localhost:8000" },
  },
});
