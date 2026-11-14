// Conferência da fala da IA: de onde veio a mensagem (qual turno) e se os
// valores em reais que ela cita estão na oferta vigente. Sem React, para o
// teste rodar no Node (testes/conferencia.teste.ts).
import type { Ficha, Mensagem, Turno } from "../api";

// "R$ 4.619,53", "R$297,14", "R$ 300": vira centavos para comparar sem float.
const REAIS = /R\$\s?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?/g;

export function centavosCitados(texto: string): number[] {
  return [...texto.matchAll(REAIS)].map(
    ([, inteiro, decimal]) => Number(inteiro.replaceAll(".", "")) * 100 + Number(decimal ?? 0),
  );
}

// A oferta guarda valores como texto ("300.00").
const centavos = (valor: string) => Math.round(Number(valor) * 100);

// Turno e resposta são gravados na mesma transação: o `now()` do Postgres dá o
// mesmo horário aos dois. A folga de 1 s cobre arredondamento na serialização.
export function turnoDaMensagem(mensagem: Mensagem, turnos: Turno[]): Turno | undefined {
  const em = Date.parse(mensagem.criada_em);
  let melhor: Turno | undefined;
  let menor = 1000;
  for (const t of turnos) {
    const distancia = Math.abs(Date.parse(t.criado_em) - em);
    if (distancia <= menor) {
      melhor = t;
      menor = distancia;
    }
  }
  return melhor;
}

export type Origem =
  | { tipo: "codigo"; turno: Turno }
  | { tipo: "modelo"; turno: Turno }
  | { tipo: "sem-registro" };

// O modelo (FAQ) nunca deveria escrever valores: um turno que chamou o `llm`
// e respondeu com reais pede conferência.
export function origemDaMensagem(mensagem: Mensagem, turnos: Turno[]): Origem {
  const turno = turnoDaMensagem(mensagem, turnos);
  if (!turno) return { tipo: "sem-registro" };
  return turno.chamadas.some((c) => c.nome === "llm") ? { tipo: "modelo", turno } : { tipo: "codigo", turno };
}

// Valores citados que não aparecem na oferta vigente (liberado, parcela ou
// seguro). `null` quando não há oferta para conferir.
export function foraDaOferta(citados: number[], oferta: Ficha["oferta"]): number[] | null {
  if (!oferta) return null;
  const conhecidos = new Set([oferta.liberado, oferta.valor_parcela, oferta.valor_seguro].map(centavos));
  return citados.filter((c) => !conhecidos.has(c));
}

export const reaisDeCentavos = (c: number) =>
  (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
