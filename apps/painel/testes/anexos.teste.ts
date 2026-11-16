// Confere tipoDoAnexo (src/anexos.ts): a lista do que o painel desenha. O que
// não está nela só pode ser baixado. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { tipoDoAnexo, rotuloDoAnexo } = await import("../src/anexos.ts");

const TABELA: [string, string][] = [
  ["image/jpeg", "imagem"],
  ["IMAGE/PNG", "imagem"],
  ["image/webp", "imagem"],
  ["application/pdf", "pdf"],
  ["application/pdf; charset=binary", "pdf"],
  ["audio/ogg; codecs=opus", "audio"],
  ["video/mp4", "video"],
  // Rodariam código do arquivo na sessão do atendente: nunca desenhados.
  ["image/svg+xml", "outro"],
  ["text/html", "outro"],
  ["application/xhtml+xml", "outro"],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "outro"],
  ["application/octet-stream", "outro"],
  ["", "outro"],
];
for (const [mime, esperado] of TABELA) assert.equal(tipoDoAnexo(mime), esperado, mime);

assert.equal(rotuloDoAnexo("pdf", "contrato.pdf"), "PDF");
assert.equal(rotuloDoAnexo("video", null), "Vídeo");
assert.equal(rotuloDoAnexo("outro", "holerite.docx"), "DOCX");
assert.equal(rotuloDoAnexo("outro", null), "Arquivo");

console.log("anexos: ok");
