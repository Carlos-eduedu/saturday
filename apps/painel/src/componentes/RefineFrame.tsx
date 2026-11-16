// RefineFrame, da React Bits (reactbits.dev), portado para TypeScript e
// reduzido ao carregamento de uma imagem: a moldura guarda o lugar, e a imagem
// sai do mosaico para a nitidez quando chega. Os estágios de geração por IA do
// original (queued, refining) ficaram de fora.
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import { Alert02Icon, Loading03Icon, RefreshIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import "./RefineFrame.css";

export type StatusQuadro = "carregando" | "pronto" | "falhou";

const ROTULO: Record<StatusQuadro, string> = {
  carregando: "Carregando",
  pronto: "",
  falhou: "Não carregou",
};

// Tamanho do bloco do mosaico em cada nível, do mais grosso ao nítido.
const NIVEIS = [48, 32, 20, 12, 8, 5, 3, 2, 1];
const PASSO_MS = 60; // por nível: ~0,5 s do mosaico à imagem
const BORDA = 28;
const FAIXAS = 14;

type Sim = { p: number; quadro: number; l: number; a: number; niveis: HTMLCanvasElement[] };

// Desenha a imagem (recortada como `object-fit: cover`) em cada nível de bloco.
function montar(s: Sim, canvas: HTMLCanvasElement, img: HTMLImageElement, dpr: number) {
  const caixa = canvas.getBoundingClientRect();
  const L = Math.max(1, Math.round(caixa.width * dpr));
  const A = Math.max(1, Math.round(caixa.height * dpr));
  s.l = canvas.width = L;
  s.a = canvas.height = A;
  const cobre = Math.max(L / img.naturalWidth, A / img.naturalHeight);
  const sl = L / cobre;
  const sa = A / cobre;
  const sx = (img.naturalWidth - sl) / 2;
  const sy = (img.naturalHeight - sa) / 2;
  s.niveis = NIVEIS.map((bloco) => {
    const cheio = document.createElement("canvas");
    cheio.width = L;
    cheio.height = A;
    const c = cheio.getContext("2d");
    if (!c) return cheio;
    if (bloco === 1) {
      c.imageSmoothingQuality = "high";
      c.drawImage(img, sx, sy, sl, sa, 0, 0, L, A);
      return cheio;
    }
    const b = Math.max(2, Math.round(bloco * dpr));
    const pequeno = document.createElement("canvas");
    pequeno.width = Math.max(1, Math.round(L / b));
    pequeno.height = Math.max(1, Math.round(A / b));
    const p = pequeno.getContext("2d");
    if (p) {
      p.imageSmoothingQuality = "high";
      p.drawImage(img, sx, sy, sl, sa, 0, 0, pequeno.width, pequeno.height);
    }
    c.imageSmoothingEnabled = false;
    c.drawImage(pequeno, 0, 0, L, A);
    return cheio;
  });
}

export function RefineFrame({
  status,
  children,
  aoTentarDeNovo,
}: {
  status: StatusQuadro;
  // O <img> da miniatura; quem usa avisa o `status` pelo onLoad/onError dele.
  children?: ReactNode;
  aoTentarDeNovo?: () => void;
}) {
  const impressao = useRef<HTMLDivElement>(null);
  const tela = useRef<HTMLCanvasElement>(null);
  const sim = useRef<Sim>({ p: 0, quadro: 0, l: 0, a: 0, niveis: [] });
  const [resolvido, setResolvido] = useState(false);

  // Layout effect: o primeiro nível do mosaico é pintado antes de a tela mostrar o quadro.
  useLayoutEffect(() => {
    if (status !== "pronto" || resolvido) return undefined;
    const s = sim.current;
    const canvas = tela.current;
    const img = impressao.current?.querySelector("img");
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || !img?.naturalWidth || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setResolvido(true);
      return undefined;
    }
    const dpr = Math.min(2, devicePixelRatio || 1);
    montar(s, canvas, img, dpr);
    const n = s.niveis.length - 1;
    const inicio = performance.now();
    const passo = (agora: number) => {
      // Pelo relógio, não por quadro: aba em segundo plano ou tela lenta não esticam a revelação.
      // (A hora do quadro pode vir um pouco antes de `inicio`: daí o piso em 0.)
      s.p = Math.min(1, Math.max(0, agora - inicio) / (n * PASSO_MS));
      const nivel = s.p * n;
      const i = Math.min(n, Math.floor(nivel + 1e-6));
      const fracao = nivel - i;
      ctx.globalAlpha = 1;
      // Índice fora da lista não desenha: um nível que falta não pode travar a revelação.
      const atual = s.niveis[i];
      const seguinte = s.niveis[i + 1];
      if (atual) ctx.drawImage(atual, 0, 0);
      if (seguinte && fracao > 0) {
        // O nível seguinte desce como uma frente, com a borda esfumada em faixas.
        const borda = BORDA * dpr;
        const frente = fracao * (s.a + borda) - borda / 2;
        const topo = Math.max(0, Math.floor(frente - borda / 2));
        if (topo > 0) ctx.drawImage(seguinte, 0, 0, s.l, topo, 0, 0, s.l, topo);
        const alturaFaixa = borda / FAIXAS;
        for (let k = 0; k < FAIXAS; k += 1) {
          const y = frente - borda / 2 + k * alturaFaixa;
          if (y + alturaFaixa <= 0 || y >= s.a) continue;
          const t = 1 - (k + 0.5) / FAIXAS;
          ctx.globalAlpha = t * t * (3 - 2 * t);
          const y0 = Math.max(0, y);
          const h0 = Math.min(s.a, y + alturaFaixa) - y0;
          if (h0 > 0) ctx.drawImage(seguinte, 0, y0, s.l, h0, 0, y0, s.l, h0);
        }
        ctx.globalAlpha = 1;
      }
      if (s.p >= 1) {
        // Solta os nove canvases: uma conversa pode ter dezenas de imagens.
        s.niveis = [];
        setResolvido(true);
        return;
      }
      s.quadro = requestAnimationFrame(passo);
    };
    passo(inicio);
    return () => cancelAnimationFrame(s.quadro);
  }, [status, resolvido]);

  return (
    <div className="refine-frame" data-status={status} data-resolvido={resolvido ? "" : undefined}>
      <div ref={impressao} className="refine-frame__print">
        {children}
      </div>
      {!resolvido && <canvas ref={tela} className="refine-frame__mosaic" aria-hidden="true" />}
      <div className="refine-frame__sweep" aria-hidden="true" />
      {status !== "pronto" && (
        <div className="refine-frame__chip">
          <span className="refine-frame__mark" data-status={status}>
            <HugeiconsIcon icon={status === "falhou" ? Alert02Icon : Loading03Icon} size={14} strokeWidth={2.2} />
          </span>
          {ROTULO[status]}
        </div>
      )}
      {status === "falhou" && aoTentarDeNovo && (
        <button type="button" className="refine-frame__retry" onClick={aoTentarDeNovo}>
          <HugeiconsIcon icon={RefreshIcon} size={16} strokeWidth={2} />
          Tentar de novo
        </button>
      )}
    </div>
  );
}
