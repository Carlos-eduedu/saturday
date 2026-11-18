// Confere qualidadeMeta (src/rotulos.ts): os quatro valores da Meta em
// português, e o que a tela não conhece aparece cru, nunca some.
import assert from "node:assert/strict";

const { qualidadeMeta } = await import("../src/rotulos.ts");

assert.deepEqual(qualidadeMeta("GREEN"), { rotulo: "Qualidade alta (verde)", tom: "alta" });
assert.deepEqual(qualidadeMeta("YELLOW"), { rotulo: "Qualidade média (amarela)", tom: "media" });
assert.deepEqual(qualidadeMeta("RED"), { rotulo: "Qualidade baixa (vermelha)", tom: "baixa" });
assert.deepEqual(qualidadeMeta("NA"), { rotulo: "Qualidade ainda não avaliada", tom: "sem" });
assert.deepEqual(qualidadeMeta("UNKNOWN"), { rotulo: "Qualidade: UNKNOWN", tom: "sem" });
assert.deepEqual(qualidadeMeta(""), { rotulo: "Qualidade: não informada", tom: "sem" });

console.log("rotulos: ok");
