import { useParams } from "react-router";
import type { Eu } from "../api";
import { AvisoDesfazer } from "../componentes/Desfazer";
import { Vazio } from "../componentes/Vazio";
import { useMidia } from "../midia";
import { Conversa } from "./Conversa";
import { Inbox } from "./Inbox";

// A partir de 1024 px, lista e conversa aberta lado a lado, como um chat; a
// ficha ganha coluna própria a partir de 1280 px. Abaixo disso, uma tela de cada vez.
export function Caixa({ eu }: { eu: Eu }) {
  const { id } = useParams();
  const lado = useMidia("(min-width: 1024px)");
  const fichaEmColuna = useMidia("(min-width: 1280px)");

  if (!lado)
    return <AvisoDesfazer>{id ? <Conversa eu={eu} /> : <Inbox eu={eu} />}</AvisoDesfazer>;
  return (
    <AvisoDesfazer>
      <div className="caixa">
        <div className="caixa-lista">
          <Inbox eu={eu} compacta aberta={id} />
        </div>
        {id ? (
          <Conversa key={id} eu={eu} fichaEmAba={!fichaEmColuna} />
        ) : (
          <Vazio
            titulo="Escolha uma conversa."
            texto="Ela abre aqui, ao lado da lista, com o histórico, a ficha e a trilha da IA."
          />
        )}
      </div>
    </AvisoDesfazer>
  );
}
