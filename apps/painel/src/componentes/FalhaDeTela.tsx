import { Component, type ReactNode } from "react";

/** Erro de renderização virava tela branca — e o painel é a única janela da
 *  equipe para o cliente. Segura o estrago, diz o que houve e oferece o
 *  caminho de volta; o detalhe técnico fica no console. */
export class FalhaDeTela extends Component<{ children: ReactNode }, { falhou: boolean }> {
  state = { falhou: false };

  static getDerivedStateFromError() {
    return { falhou: true };
  }

  componentDidCatch(erro: unknown) {
    console.error("Falha ao desenhar o painel", erro);
  }

  render() {
    if (!this.state.falhou) return this.props.children;
    return (
      <div className="centro" role="alert">
        <h2>Esta tela não abriu</h2>
        <p>Algo falhou ao desenhar o painel. Recarregar costuma resolver.</p>
        <button type="button" className="principal" onClick={() => window.location.reload()}>
          Recarregar
        </button>
      </div>
    );
  }
}
