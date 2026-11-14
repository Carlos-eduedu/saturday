// Confere src/paginas/conferencia.ts: valores citados, turno de cada fala e
// a diferença para a oferta vigente. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { centavosCitados, foraDaOferta, origemDaMensagem, turnoDaMensagem } = await import(
  "../src/paginas/conferencia.ts"
);

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
  turno_id: null as number | null,
  chave_mensagem: null as string | null,
  anexos: [],
};
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
