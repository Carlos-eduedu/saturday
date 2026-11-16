import type { EstadoMembro } from "../api";
import { ROTULO_ESTADO } from "../membros";

// Disponível, ausente ou fora do painel: o ponto e o texto dizem a mesma coisa,
// para a cor nunca ser o único sinal.
export function EstadoDoMembro({ estado }: { estado: EstadoMembro }) {
  return (
    <span className={`estado-membro estado-membro--${estado}`}>
      <span className="estado-membro__ponto" aria-hidden="true" />
      {ROTULO_ESTADO[estado]}
    </span>
  );
}
