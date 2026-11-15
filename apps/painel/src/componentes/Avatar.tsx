// A pessoa da equipe: a foto, quando há, ou as iniciais do nome.
export const iniciais = (nome: string) =>
  nome
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("") || "?";

export function Avatar({
  nome,
  foto,
  tamanho = 34,
}: {
  nome: string;
  foto: string | null;
  tamanho?: number;
}) {
  const estilo = { width: tamanho, height: tamanho, fontSize: Math.round(tamanho * 0.38) };
  return foto ? (
    <img className="avatar" src={foto} alt="" width={tamanho} height={tamanho} style={estilo} />
  ) : (
    <span className="avatar" aria-hidden="true" style={estilo}>
      {iniciais(nome)}
    </span>
  );
}
