// Confere detalheDoErro (src/api.ts): o texto de falha que a tela mostra fica em
// português. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { detalheDoErro } = await import("../src/api.ts");

// Motivo dado pela nossa API passa como veio.
assert.equal(detalheDoErro(409, { detail: "conversa já assumida" }), "conversa já assumida");

// Validação: só as mensagens dos nossos validadores, sem o prefixo do pydantic.
assert.equal(
  detalheDoErro(422, {
    detail: [
      { type: "value_error", msg: "Value error, CPF inválido" },
      { type: "missing", msg: "Field required" },
      { type: "value_error", msg: "Value error, e-mail inválido" },
    ],
  }),
  "CPF inválido; e-mail inválido",
);

// Mensagem pronta do pydantic (inglês) cai no texto padrão do status.
assert.equal(
  detalheDoErro(422, { detail: [{ type: "uuid_parsing", msg: "Input should be a valid UUID, invalid character" }] }),
  "O servidor recusou o pedido: algum dado veio em formato errado.",
);

// Texto automático do Starlette e corpo sem JSON também.
assert.equal(detalheDoErro(404, { detail: "Not Found" }), "Não encontrado: pode ter sido apagado ou o link está errado.");
assert.equal(detalheDoErro(502, null), "O servidor falhou ao responder. Tente de novo em instantes.");
assert.equal(detalheDoErro(418, {}), "Não deu certo (erro 418).");

console.log("erros: ok");
