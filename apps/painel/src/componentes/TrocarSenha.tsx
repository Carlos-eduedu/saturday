import { type FormEvent, type ReactNode, useId, useState } from "react";
import { api, ErroApi, mensagemDeFalha } from "../api";
import { recusaDaSenhaNova, SENHA_MINIMA } from "../membros";

// A pessoa troca a própria senha informando a atual (decisão 0030). O mesmo
// formulário serve em "Seu perfil" e na troca obrigatória do primeiro acesso;
// quem chama dá o título e a classe. As regras são da API; a conferência aqui
// só poupa a ida ao servidor.
export function TrocarSenha({
  className,
  email,
  acao = "Trocar senha",
  cabecalho,
  rodape,
  aoTrocar,
}: {
  className: string;
  email: string;
  acao?: string;
  cabecalho: ReactNode;
  rodape?: ReactNode;
  // Não pode falhar: a senha já trocou.
  aoTrocar: () => void;
}) {
  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [repete, setRepete] = useState("");
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const idErro = useId();

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setAviso("");
    const recusa = recusaDaSenhaNova(atual, nova, repete);
    setErro(recusa);
    if (recusa) return;
    setOcupado(true);
    try {
      await api.trocarSenha(atual, nova);
      setAtual("");
      setNova("");
      setRepete("");
      setAviso("Senha trocada. As suas outras sessões foram encerradas.");
      aoTrocar();
    } catch (e) {
      // Como no login, o aviso do bloqueio vai junto: a API não diz quantas
      // tentativas faltam.
      setErro(
        e instanceof ErroApi && e.status === 422 && e.message === "senha atual inválida"
          ? "A senha atual não confere. Depois de 5 tentativas erradas o acesso fica bloqueado por 15 minutos e você sai do painel."
          : mensagemDeFalha(e, "trocar a senha"),
      );
    } finally {
      setOcupado(false);
    }
  }

  return (
    <form className={className} onSubmit={enviar} noValidate>
      {cabecalho}
      {/* Fora da tela: diz ao gerenciador de senhas de quem é a senha. */}
      <input type="email" name="email" autoComplete="username" value={email} readOnly hidden />
      <label>
        Senha atual
        <input
          type="password"
          name="senha-atual"
          value={atual}
          onChange={(e) => setAtual(e.target.value)}
          autoComplete="current-password"
          maxLength={256}
          aria-describedby={erro ? idErro : undefined}
          required
        />
      </label>
      <label>
        Senha nova
        <input
          type="password"
          name="senha-nova"
          value={nova}
          onChange={(e) => setNova(e.target.value)}
          placeholder={`Pelo menos ${SENHA_MINIMA} caracteres`}
          autoComplete="new-password"
          maxLength={256}
          aria-describedby={erro ? idErro : undefined}
          required
        />
      </label>
      <label>
        Repita a senha nova
        <input
          type="password"
          name="senha-repete"
          value={repete}
          onChange={(e) => setRepete(e.target.value)}
          autoComplete="new-password"
          maxLength={256}
          aria-describedby={erro ? idErro : undefined}
          required
        />
      </label>
      {erro && (
        <p id={idErro} className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && (
        <p className="confere" role="status">
          {aviso}
        </p>
      )}
      <button type="submit" className="principal" disabled={ocupado || !atual || !nova || !repete}>
        {ocupado ? "Trocando…" : acao}
      </button>
      {rodape}
    </form>
  );
}
