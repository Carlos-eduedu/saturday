// Confere permissoesDa (src/permissoes.ts): o que cada perfil pode em cada
// estado de atendimento. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { permissoesDa } = await import("../src/permissoes.ts");

const ana = { id: "ana", perfil: "atendente" };
const gestor = { id: "gil", perfil: "gestor" };
const conversa = (atendimento: string, atendente_id: string | null = null) => ({
  atendimento,
  atendente_id,
  canal: "whatsapp",
  janela_aberta: true,
});

// Colunas: minha, podeAssumir, tomaDeOutro, podeDevolver, podeMexer.
const TABELA: [string, ReturnType<typeof conversa>, typeof ana, boolean[]][] = [
  ["ia, atendente", conversa("ia"), ana, [false, true, false, false, false]],
  ["ia, gestor", conversa("ia"), gestor, [false, true, false, false, true]],
  ["handoff, atendente", conversa("handoff"), ana, [false, true, false, true, false]],
  ["handoff, gestor", conversa("handoff"), gestor, [false, true, false, true, true]],
  ["assumida por mim", conversa("assumida", "ana"), ana, [true, false, false, true, true]],
  ["assumida por outro, atendente", conversa("assumida", "bia"), ana, [false, false, false, false, false]],
  ["assumida por outro, gestor", conversa("assumida", "bia"), gestor, [false, true, true, true, true]],
  ["assumida pelo gestor, ele mesmo", conversa("assumida", "gil"), gestor, [true, false, false, true, true]],
];
for (const [caso, c, eu, esperado] of TABELA) {
  const p = permissoesDa(c, eu);
  assert.deepEqual([p.minha, p.podeAssumir, p.tomaDeOutro, p.podeDevolver, p.podeMexer], esperado, caso);
}

// Janela: só o WhatsApp oficial fecha; Evolution escreve sempre.
const janela = (canal: string, janela_aberta: boolean) =>
  permissoesDa({ ...conversa("ia"), canal, janela_aberta }, ana).janelaAberta;
assert.equal(janela("whatsapp", true), true);
assert.equal(janela("whatsapp", false), false);
assert.equal(janela("evolution", false), true);

console.log("permissoes: ok");
