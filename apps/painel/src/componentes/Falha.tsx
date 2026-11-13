// Carregar falhou: diz o quê e deixa tentar de novo. Nunca no lugar de um
// `Vazio` — "nenhum alerta" com a API fora esconderia o que a equipe precisa ver.
export function Falha({
  titulo = "Não deu para carregar.",
  texto,
  aoTentar,
}: {
  titulo?: string;
  texto: string;
  aoTentar: () => void;
}) {
  return (
    <div className="vazio falha" role="alert">
      <p className="vazio-titulo">{titulo}</p>
      <p>{texto}</p>
      <button type="button" onClick={aoTentar}>
        Tentar de novo
      </button>
    </div>
  );
}
