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
      // e-mail existe nem se a conta está bloqueada. Por isso o aviso do
      // bloqueio vai junto. Falha de rede (status 0) ou 5xx é outra coisa —
      // dizer "senha inválida" ali manda a pessoa tentar de novo com a senha certa.
      setErro(
        e instanceof ErroApi && e.status === 401
          ? "E-mail ou senha não conferem. Depois de 5 tentativas erradas o acesso fica bloqueado por 15 minutos; se esqueceu a senha, peça a um gestor para redefinir."
          : e instanceof ErroApi
            ? e.message
            : "Não consegui falar com o servidor. Confira a conexão e tente de novo.",
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="login" onSubmit={enviar}>
      <h1>Saturday</h1>
      <p className="nota">Acompanhe o que a IA faz no WhatsApp e assuma a conversa na hora certa.</p>
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
        {enviando ? "Entrando…" : "Entrar"}
      </button>
      <p className="nota">Acesso só da equipe. Cada ação no painel fica registrada na auditoria.</p>
    </form>
  );
}
