// Valor animável mínimo, no lugar do `motion` no SwipeRow: guarda um número,
// avisa quem desenha a cada mudança e anima por tempo (curva cúbica) ou por
// mola, no requestAnimationFrame. Só o que o gesto de arrastar precisa.

export type Curva = [number, number, number, number];

export type Opcoes =
  | { duration: number; ease: Curva }
  | { type: "spring"; duration: number; bounce: number; velocity?: number };

export class Valor {
  aoMudar: () => void = () => undefined;
  private v: number;
  private quadro = 0;

  constructor(inicial: number) {
    this.v = inicial;
  }

  get(): number {
    return this.v;
  }

  set(v: number): void {
    this.stop();
    this.escrever(v);
  }

  stop(): void {
    cancelAnimationFrame(this.quadro);
    this.quadro = 0;
  }

  // Resolve ao chegar no alvo; uma animação interrompida (stop/set) não resolve.
  animar(alvo: number, o: Opcoes): Promise<void> {
    this.stop();
    return new Promise((pronto) => {
      const de = this.v;
      const inicio = performance.now();
      if ("ease" in o) {
        const curva = cubica(o.ease);
        const passo = (agora: number) => {
          const t = Math.min(1, (agora - inicio) / 1000 / o.duration);
          this.escrever(de + (alvo - de) * curva(t));
          if (t < 1) this.quadro = requestAnimationFrame(passo);
          else {
            this.quadro = 0;
            pronto();
          }
        };
        this.quadro = requestAnimationFrame(passo);
        return;
      }
      // Mola amortecida: `bounce` 0 é crítica (sem passar do alvo); a
      // frequência faz ela assentar perto de `duration`.
      const zeta = Math.min(1, Math.max(0.05, 1 - o.bounce));
      const omega = 6.64 / o.duration;
      let vel = o.velocity ?? 0;
      let anterior = inicio;
      const passo = (agora: number) => {
        let dt = Math.min(1 / 30, (agora - anterior) / 1000);
        anterior = agora;
        let x = this.v;
        // Passos de 1 ms: estável mesmo com quadro lento.
        while (dt > 0) {
          const h = Math.min(dt, 0.001);
          const acel = -omega * omega * (x - alvo) - 2 * zeta * omega * vel;
          vel += acel * h;
          x += vel * h;
          dt -= h;
        }
        if (Math.abs(x - alvo) < 0.5 && Math.abs(vel) < 10) {
          this.quadro = 0;
          this.escrever(alvo);
          pronto();
          return;
        }
        this.escrever(x);
        this.quadro = requestAnimationFrame(passo);
      };
      this.quadro = requestAnimationFrame(passo);
    });
  }

  private escrever(v: number): void {
    this.v = v;
    this.aoMudar();
  }
}

// cubic-bezier(x1, y1, x2, y2) como função de 0..1 → 0..1 (Newton, depois bisseção).
export function cubica([x1, y1, x2, y2]: Curva): (t: number) => number {
  const bx = (t: number) => 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t;
  const by = (t: number) => 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t;
  const dbx = (t: number) =>
    3 * (1 - t) * (1 - t) * x1 + 6 * (1 - t) * t * (x2 - x1) + 3 * t * t * (1 - x2);
  return (x: number) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) {
      const d = dbx(t);
      if (Math.abs(d) < 1e-6) break;
      const proximo = t - (bx(t) - x) / d;
      if (proximo < 0 || proximo > 1) break;
      t = proximo;
    }
    if (Math.abs(bx(t) - x) > 1e-4) {
      let lo = 0;
      let hi = 1;
      for (let i = 0; i < 30; i++) {
        t = (lo + hi) / 2;
        if (bx(t) < x) lo = t;
        else hi = t;
      }
    }
    return by(t);
  };
}
