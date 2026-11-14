// Confere src/paginas/conferencia.ts: valores citados, turno de cada fala e
// a diferença para a oferta vigente. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { centavosCitados, foraDaOferta, origemDaMensagem } = await import("../src/paginas/conferencia.ts");

assert.deepEqual(centavosCitados("R$ 4.619,53 liberados, 36 de R$300,00 e R$ 1.000"), [461953, 30000, 100000]);
assert.deepEqual(centavosCitados("Taxa de 4% a.m., sem valores"), []);

const oferta = {
  liberado: "4619.53",
  valor_parcela: "300.00",
  numero_parcelas: 36,
  taxa_mensal: "4",
  cet_mensal: "4.98",
  valor_seguro: "503.32",
  seguro_aplicado: true,
  limitado_ao_teto: false,
};
assert.deepEqual(foraDaOferta([461953, 30000, 50332], oferta), []);
assert.deepEqual(foraDaOferta([29714, 30000], oferta), [29714]);
assert.equal(foraDaOferta([29714], null), null);

const turno = (criado_em: string, chamadas: string[]) => ({
  id: 1,
  criado_em,
  caminho: ["clt"],
  status: null,
  motivo: null,
  etapa: null,
  classificacao: null,
  chamadas: chamadas.map((nome) => ({
    nome,
    latencia_ms: 1,
    status: "ok",
    custo_usd: null,
    tokens_entrada: null,
    tokens_saida: null,
  })),
  custo_usd: null,
  tokens: null,
  duracao_ms: null,
  erro: null,
});
const mensagem = {
  id: 1,
  direcao: "saida" as const,
  autor: "ia" as const,
  usuario_id: null,
  conteudo: "R$ 300,00",
  status_entrega: null,
  criada_em: "2026-11-14T01:37:25.416945+00:00",
  anexos: [],
};
assert.equal(origemDaMensagem(mensagem, []).tipo, "sem-registro");
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:37:25.416945Z", ["granatech"])]).tipo, "codigo");
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:37:25.416Z", ["jev", "llm"])]).tipo, "modelo");
// Turno de outro momento não é a origem.
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:30:00Z", ["llm"])]).tipo, "sem-registro");

console.log("conferencia: ok");
