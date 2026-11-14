// Seletor de abas em pílula (conversa no celular, aba Agente).
export function Abas<T extends string>({
  rotulo,
  opcoes,
  valor,
  mudar,
}: {
  rotulo: string;
  opcoes: [T, string][];
  valor: T;
  mudar: (v: T) => void;
}) {
  return (
    <div role="tablist" aria-label={rotulo} className="abas-laterais">
      {opcoes.map(([v, texto]) => (
        <button
          key={v}
          type="button"
          role="tab"
          aria-selected={valor === v}
          className={valor === v ? "ativo" : ""}
          onClick={() => mudar(v)}
        >
          {texto}
        </button>
      ))}
    </div>
  );
}
