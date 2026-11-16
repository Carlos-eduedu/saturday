// Confere rotuloDaAcao (src/membros.ts): toda ação da auditoria vira frase, e
// a que a tela não conhece aparece com o próprio código, nunca some.
import assert from "node:assert/strict";

const { rotuloDaAcao, conversas } = await import("../src/membros.ts");

const TABELA: [string, string][] = [
  ["assumir", "Assumiu a conversa"],
  ["conversa:editar_ficha", "Editou a ficha do cliente"],
  ["revelar:cpf", "Revelou o CPF de um cliente"],
  ["revelar:nome_mae", "Revelou nome_mae de um cliente"],
  ["canal_desconectar", "Mexeu nos canais"],
  ["resposta_rapida:criar", "Editou as respostas rápidas"],
  ["acao_que_nao_existe", "acao_que_nao_existe"],
];
for (const [acao, esperado] of TABELA) assert.equal(rotuloDaAcao(acao), esperado, acao);

assert.equal(conversas(0), "0 conversas");
assert.equal(conversas(1), "1 conversa");
assert.equal(conversas(7), "7 conversas");

console.log("membros: ok");
