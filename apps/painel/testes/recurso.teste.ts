// Confere Recurso (src/recurso.ts): carga, recarga por aviso, reconexão e
// descarte de resposta velha. Roda com `npm run teste`.
import assert from "node:assert/strict";

const { Recurso } = await import("../src/recurso.ts");

// Cada busca fica pendente até o teste resolver ou rejeitar, na ordem que quiser.
function buscas() {
  const pendentes: { resolver: (v: string) => void; rejeitar: (e: unknown) => void }[] = [];
  const buscar = () =>
    new Promise<string>((resolver, rejeitar) => {
      pendentes.push({ resolver, rejeitar });
    });
  return { pendentes, buscar };
}
const assentar = () => new Promise((r) => setTimeout(r, 0));

// Carga: o dado chega com a chave dele e os ouvintes são avisados.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>();
  let avisos = 0;
  recurso.assinar(() => avisos++);
  recurso.apontar("a", buscar);
  assert.equal(recurso.ler().dado, null);
  pendentes[0].resolver("um");
  await assentar();
  assert.deepEqual(recurso.ler(), { dado: "um", chaveDoDado: "a", falha: null, chaveDaFalha: null });
  assert.equal(avisos, 2);
}

// Falha ao recarregar mantém o dado; a carga seguinte que dá certo limpa a falha.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>();
  recurso.apontar("a", buscar);
  pendentes[0].resolver("um");
  await assentar();
  recurso.carregar();
  const erro = new Error("fora do ar");
  pendentes[1].rejeitar(erro);
  await assentar();
  assert.deepEqual(recurso.ler(), { dado: "um", chaveDoDado: "a", falha: erro, chaveDaFalha: "a" });
  recurso.carregar();
  pendentes[2].resolver("dois");
  await assentar();
  assert.deepEqual(recurso.ler(), { dado: "dois", chaveDoDado: "a", falha: null, chaveDaFalha: null });
}

// Avisos: reconexão sempre recarrega; os demais, só os que a tela pediu.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>();
  recurso.apontar("a", buscar);
  const soAlerta = (aviso: { tipo: string }) => aviso.tipo === "alerta";
  recurso.avisar({ tipo: "mensagem" }, soAlerta);
  assert.equal(pendentes.length, 1);
  recurso.avisar({ tipo: "alerta" }, soAlerta);
  assert.equal(pendentes.length, 2);
  recurso.avisar({ tipo: "reconectado" }, soAlerta);
  assert.equal(pendentes.length, 3);
  recurso.avisar({ tipo: "reconectado" });
  assert.equal(pendentes.length, 4);
  recurso.avisar({ tipo: "alerta" });
  assert.equal(pendentes.length, 4);
}

// Resposta velha: só a do último pedido vale, chegue ela antes ou depois.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>();
  recurso.apontar("a", buscar);
  recurso.carregar();
  pendentes[1].resolver("nova");
  await assentar();
  pendentes[0].resolver("velha");
  await assentar();
  assert.equal(recurso.ler().dado, "nova");
  recurso.carregar();
  pendentes[2].rejeitar(new Error("velha"));
  recurso.carregar();
  pendentes[3].resolver("mais nova");
  await assentar();
  assert.equal(recurso.ler().dado, "mais nova");
  assert.equal(recurso.ler().falha, null);
}

// Trocar a chave esconde o dado anterior, e a resposta dele não volta.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>();
  recurso.apontar("a", buscar);
  pendentes[0].resolver("de a");
  await assentar();
  recurso.carregar();
  recurso.apontar("b", buscar);
  assert.equal(recurso.ler().dado, null);
  pendentes[1].resolver("de a, atrasada");
  await assentar();
  assert.equal(recurso.ler().dado, null);
  pendentes[2].resolver("de b");
  await assentar();
  assert.deepEqual(recurso.ler(), { dado: "de b", chaveDoDado: "b", falha: null, chaveDaFalha: null });
}

// Com `manter`, o dado anterior fica à vista, marcado com a chave dele.
{
  const { pendentes, buscar } = buscas();
  const recurso = new Recurso<string>(true);
  recurso.apontar("a", buscar);
  pendentes[0].resolver("de a");
  await assentar();
  recurso.apontar("b", buscar);
  assert.deepEqual(recurso.ler(), { dado: "de a", chaveDoDado: "a", falha: null, chaveDaFalha: null });
  pendentes[1].resolver("de b");
  await assentar();
  assert.equal(recurso.ler().chaveDoDado, "b");
}

console.log("recurso: ok");
