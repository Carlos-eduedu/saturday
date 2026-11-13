// Confere src/componentes/movimento.ts sem navegador: curva cúbica, mola
// chegando no alvo e stop(). Roda com `npm run teste` (Node com strip-types).
import assert from "node:assert/strict";

// requestAnimationFrame falso: avança 16 ms por quadro.
let agora = 0;
let proximoId = 1;
const fila = new Map<number, (t: number) => void>();
globalThis.performance = { now: () => agora } as Performance;
globalThis.requestAnimationFrame = (f: FrameRequestCallback) => (fila.set(proximoId, f), proximoId++);
globalThis.cancelAnimationFrame = (id: number) => void fila.delete(id);
const rodar = (quadros: number) => {
  for (let i = 0; i < quadros && fila.size; i++) {
    agora += 16;
    const [id, f] = fila.entries().next().value!;
    fila.delete(id);
    f(agora);
  }
};

const { Valor, cubica } = await import("../src/componentes/movimento.ts");

const linear = cubica([0, 0, 1, 1]);
for (const t of [0, 0.25, 0.5, 0.9, 1]) assert.ok(Math.abs(linear(t) - t) < 1e-3, `linear ${t}`);
const easeOut = cubica([0.23, 1, 0.32, 1]);
assert.ok(easeOut(0.2) > 0.6, "ease-out sobe rápido no começo");
assert.ok(easeOut(0.5) < 1 && easeOut(1) === 1);

for (const opcoes of [
  { type: "spring", duration: 0.3, bounce: 0, velocity: 0 },
  { type: "spring", duration: 0.4, bounce: 0.2, velocity: -1500 },
  { duration: 0.2, ease: [0.23, 1, 0.32, 1] },
]) {
  const v = new Valor(0);
  let chegou = false;
  v.animar(-300, opcoes).then(() => (chegou = true));
  rodar(200);
  await Promise.resolve();
  assert.equal(v.get(), -300, JSON.stringify(opcoes));
  assert.ok(chegou, `resolveu ${JSON.stringify(opcoes)}`);
}

// Mola crítica (bounce 0) não passa do alvo.
const critica = new Valor(0);
let minimo = 0;
critica.aoMudar = () => (minimo = Math.min(minimo, critica.get()));
critica.animar(-100, { type: "spring", duration: 0.3, bounce: 0 });
rodar(200);
assert.ok(minimo >= -100.5, `passou do alvo: ${minimo}`);

// stop() interrompe e não resolve.
const parada = new Valor(0);
let resolveu = false;
parada.animar(100, { duration: 1, ease: [0, 0, 1, 1] }).then(() => (resolveu = true));
rodar(5);
parada.stop();
rodar(100);
await Promise.resolve();
assert.ok(!resolveu && parada.get() < 100, "stop interrompe");
console.log("movimento.ts ok");
