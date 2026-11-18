// Confere src/paginas/conferencia.ts: valores citados, turno de cada fala e
// a diferença para a oferta vigente. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { centavosCitados, foraDaOferta, ofertaDaFala, origemDaMensagem, turnoDaMensagem } =
  await import("../src/paginas/conferencia.ts");

assert.deepEqual(centavosCitados("R$ 4.619,53 liberados, 36 de R$300,00 e R$ 1.000"), [461953, 30000, 100000]);
assert.deepEqual(centavosCitados("Taxa de 4% a.m., sem valores"), []);

// Os valores chegam prontos do servidor, de qualquer ramo: centavos (CLT, C6,
// iCred) ou reais inteiros (a faixa da portabilidade).
const oferta = { ramo: "clt", valores: ["4619.53", "300.00", "503.32"] };
assert.deepEqual(foraDaOferta([461953, 30000, 50332], oferta), []);
assert.deepEqual(foraDaOferta([29714, 30000], oferta), [29714]);
assert.equal(foraDaOferta([29714], null), null);
const portabilidade = { ramo: "portabilidade", valores: ["2469", "3001"] };
assert.deepEqual(foraDaOferta(centavosCitados("entre R$ 2.469 e R$ 3.001"), portabilidade), []);
assert.deepEqual(foraDaOferta(centavosCitados("em torno de R$ 3.500,00"), portabilidade), [350000]);

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
  turno_id: null as number | null,
  chave_mensagem: null as string | null,
  ramo_da_oferta: null as string | null,
  anexos: [],
};

// A fala fixa de oferta é conferida contra a oferta do próprio ramo; a
// resposta do modelo, contra a vigente.
const ofertas = {
  oferta_vigente: { ramo: "portabilidade", situacao: "vigente", valores: ["2469", "3001"] },
  ofertas: {
    contrato_novo: { situacao: "recusada", valores: ["4321.09", "99.00"] },
    portabilidade: { situacao: "vigente", valores: ["2469", "3001"] },
  },
};
const ofertaDoC6 = { ...mensagem, turno_id: 1, ramo_da_oferta: "contrato_novo" };
assert.deepEqual(ofertaDaFala(ofertaDoC6, ofertas), {
  ramo: "contrato_novo",
  valores: ["4321.09", "99.00"],
});
assert.deepEqual(ofertaDaFala(mensagem, ofertas), { ramo: "portabilidade", valores: ["2469", "3001"] });
// A oferta do ramo saiu do estado: nada para comparar, nunca a de outro ramo.
assert.equal(ofertaDaFala({ ...ofertaDoC6, ramo_da_oferta: "icred" }, ofertas), null);
assert.equal(ofertaDaFala(mensagem, null), null);
assert.equal(origemDaMensagem(mensagem, []).tipo, "sem-registro");
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:37:25.416945Z", ["granatech"])]).tipo, "codigo");
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:37:25.416Z", ["jev", "llm"])]).tipo, "modelo");
// Turno de outro momento não é a origem.
assert.equal(origemDaMensagem(mensagem, [turno("2026-11-14T01:30:00Z", ["llm"])]).tipo, "sem-registro");

// Com `turno_id` (decisão 0018) vale o id, não o horário, e a chave diz a origem.
const outro = { ...turno("2026-11-14T01:37:25.416945Z", ["llm"]), id: 2 };
const doTurno1 = turno("2026-11-14T01:30:00Z", ["granatech"]);
const fixa = { ...mensagem, turno_id: 1, chave_mensagem: "aviso_teto+oferta" };
assert.equal(turnoDaMensagem(fixa, [outro, doTurno1]), doTurno1);
assert.deepEqual(origemDaMensagem(fixa, [outro, doTurno1]), {
  tipo: "fixa",
  chave: "aviso_teto+oferta",
  turno: doTurno1,
});
const doModelo = { ...mensagem, turno_id: 1 };
assert.deepEqual(origemDaMensagem(doModelo, [doTurno1]), { tipo: "modelo", exato: true, turno: doTurno1 });
// Turno fora da lista: a chave continua valendo.
assert.equal(origemDaMensagem({ ...fixa, turno_id: 99 }, [outro]).tipo, "fixa");

console.log("conferencia: ok");
