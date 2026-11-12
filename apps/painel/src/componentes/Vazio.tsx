// Tela vazia que diz o que aparece ali, em vez de só "nada aqui".
export function Vazio({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <div className="vazio">
      <p className="vazio-titulo">{titulo}</p>
      <p>{texto}</p>
    </div>
  );
}
