import { useParams } from "react-router";
import type { Eu } from "../api";
import { AvisoDesfazer } from "../componentes/Desfazer";
import { Vazio } from "../componentes/Vazio";
import { useMidia } from "../midia";
import { Conversa } from "./Conversa";
import { Inbox } from "./Inbox";

// A partir de 1024 px, lista e conversa aberta lado a lado, como um chat; a
// ficha ganha coluna própria a partir de 1280 px. Abaixo disso, uma tela de cada vez.
// A árvore é a mesma em toda largura (o CSS esconde a lista no celular com a
// conversa aberta): redimensionar ou girar não remonta lista nem conversa, e a
// lista não volta a carregar do zero.
export function Caixa({ eu }: { eu: Eu }) {
  const { id } = useParams();
  const lado = useMidia("(min-width: 1024px)");
  const fichaEmColuna = useMidia("(min-width: 1280px)");

  return (
    <AvisoDesfazer>
      <div className={id ? "caixa com-aberta" : "caixa"}>
        <div className="caixa-lista">
          <Inbox eu={eu} compacta={lado} aberta={id} />
        </div>
        {id ? (
          <Conversa key={id} eu={eu} fichaEmAba={!fichaEmColuna} />
        ) : (
          lado && (
            <Vazio
              titulo="Escolha uma conversa."
              texto="Ela abre aqui, ao lado da lista, com o histórico, a ficha e a trilha da IA."
            />
          )
        )}
      </div>
    </AvisoDesfazer>
  );
}
