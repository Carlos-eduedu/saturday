import { type FormEvent, useState } from "react";
import { api, ErroApi, type Eu } from "../api";

export function Login({ aoEntrar }: { aoEntrar: (eu: Eu) => void }) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    setErro("");
    try {
      aoEntrar(await api.entrar(email, senha));
    } catch (e) {
      // A API responde 401 para qualquer recusa, de propósito: não entrega se o
      // e-mail existe. Falha de rede ou 5xx é outra coisa — dizer "senha
      // inválida" ali manda a pessoa tentar de novo com a senha certa.
      setErro(
        e instanceof ErroApi
          ? "E-mail ou senha inválidos."
          : "Não consegui falar com o servidor. Confira a conexão e tente de novo.",
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="login" onSubmit={enviar}>
      <h1>Saturday</h1>
      <p className="nota">Painel da equipe de atendimento</p>
      <label>
        E-mail
        <input
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label>
        Senha
        <input
          type="password"
          autoComplete="current-password"
          required
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
        />
      </label>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      <button type="submit" disabled={enviando}>
        Entrar
      </button>
    </form>
  );
}
