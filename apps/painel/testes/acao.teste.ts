// Confere criarAgir (src/acao.ts): uma ação por vez, aviso ou erro no fim e a
// tela recarregada nos dois casos. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { criarAgir } = await import("../src/acao.ts");

const visto = { erro: "", aviso: "", recargas: 0 };
const agir = criarAgir({
  erro: (t: string) => (visto.erro = t),
  aviso: (t: string) => (visto.aviso = t),
  depois: () => visto.recargas++,
  falha: (e: unknown) => `falhou: ${String(e)}`,
  andamento: "rodando…",
});

// Enquanto a primeira não termina, a segunda é ignorada e nem começa.
let soltar = (_: number) => {};
let chamadas = 0;
const lenta = () => {
  chamadas++;
  return new Promise<number>((resolve) => (soltar = resolve));
};
const primeira = agir(lenta, (n: number) => `feito ${n}`);
assert.equal(visto.aviso, "rodando…");
assert.equal(await agir(lenta, "não roda"), false);
assert.equal(chamadas, 1);
soltar(7);
assert.equal(await primeira, true);
assert.deepEqual(visto, { erro: "", aviso: "feito 7", recargas: 1 });

// Terminada, a próxima roda; a falha vira erro, limpa o aviso e recarrega.
assert.equal(await agir(() => Promise.reject("x"), "não aparece"), false);
assert.deepEqual(visto, { erro: "falhou: x", aviso: "", recargas: 2 });

// A ação seguinte limpa o erro anterior.
assert.equal(await agir(() => Promise.resolve(), "ok"), true);
assert.deepEqual(visto, { erro: "", aviso: "ok", recargas: 3 });

console.log("acao: ok");
