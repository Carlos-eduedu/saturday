import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Vazio } from "../componentes/Vazio";
import { api, type Eu, ErroApi, type Perfil, type UsuarioGestao } from "../api";

// Aba Usuários (decisão 0012), só para gestor: cadastrar, editar, redefinir
// senha, desbloquear, desativar e reativar. Nunca apagar: a auditoria continua
// dizendo quem fez o quê. As travas (não desativar a si mesmo, nunca ficar sem
// gestor) são da API; a tela só esconde o que já sabe que vai ser recusado.

const SENHA_MINIMA = 12;

const ROTULO_PERFIL: Record<Perfil, string> = { atendente: "Atendente", gestor: "Gestor" };

function mensagemDe(erro: unknown): string {
  return erro instanceof ErroApi ? erro.message : "falha inesperada";
}

function situacao(u: UsuarioGestao): string {
  if (u.situacao === "bloqueado" && u.bloqueado_ate) {
    const hora = new Date(u.bloqueado_ate).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });
    return `bloqueado até ${hora}`;
  }
  return u.situacao;
}

export function Usuarios({ eu }: { eu: Eu }) {
  const [usuarios, setUsuarios] = useState<UsuarioGestao[] | null>(null);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [editando, setEditando] = useState<string | null>(null);

  const carregar = useCallback(() => {
    api
      .gestaoUsuarios()
      .then(setUsuarios)
      .catch((e: unknown) => setErro(mensagemDe(e)));
  }, []);
  useEffect(carregar, [carregar]);

  async function agir(acao: () => Promise<unknown>, feito: string): Promise<boolean> {
    setErro("");
    setAviso("");
    try {
      await acao();
      setAviso(feito);
      return true;
    } catch (e) {
      setErro(mensagemDe(e));
      return false;
    } finally {
      carregar();
    }
  }

  if (!usuarios) return <p className="centro">{erro || "Carregando…"}</p>;
  const selecionado = usuarios.find((u) => u.id === editando) ?? null;

  return (
    <div className="canais usuarios">
      <h1 className="titulo-tela">Usuários</h1>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="confere">{aviso}</p>}

      <section>
        <h2>Equipe</h2>
        {usuarios.length === 0 ? (
          <Vazio titulo="Nenhum usuário." texto="Cadastre o primeiro abaixo." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Nome</th>
                <th>E-mail</th>
                <th>Perfil</th>
                <th>Situação</th>
                <th>Cadastro</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id} className={u.situacao === "desativado" ? "desativado" : undefined}>
                  <td>
                    {u.nome}
                    {u.id === eu.id && <small> (você)</small>}
                  </td>
                  <td data-rotulo="E-mail">{u.email}</td>
                  <td data-rotulo="Perfil">{ROTULO_PERFIL[u.perfil]}</td>
                  <td data-rotulo="Situação">
                    <span className={`situacao-usuario situacao-${u.situacao}`}>
                      {situacao(u)}
                    </span>
                  </td>
                  <td data-rotulo="Cadastro">
                    {new Date(u.criado_em).toLocaleDateString("pt-BR")}
                  </td>
                  <td className="acoes">
                    <button type="button" onClick={() => setEditando(u.id)}>
                      Editar
                    </button>
                    {u.situacao === "desativado" ? (
                      <button
                        type="button"
                        onClick={() => agir(() => api.reativarUsuario(u.id), `${u.nome} reativado.`)}
                      >
                        Reativar
                      </button>
                    ) : (
                      u.id !== eu.id && (
                        <button
                          type="button"
                          className="perigo"
                          onClick={() => {
                            const conversas =
                              u.conversas_assumidas > 0
                                ? ` ${u.conversas_assumidas} conversa(s) assumida(s) por ${u.nome} voltam para "aguardando humano".`
                                : "";
                            if (
                              !window.confirm(
                                `Desativar ${u.nome}? A pessoa sai do painel na hora e não entra mais.${conversas}`,
                              )
                            )
                              return;
                            agir(
                              () => api.desativarUsuario(u.id),
                              `${u.nome} desativado.`,
                            );
                          }}
                        >
                          Desativar
                        </button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <NovoUsuario agir={agir} />
      </section>

      {selecionado && (
        <EdicaoUsuario
          key={selecionado.id}
          usuario={selecionado}
          ehVoce={selecionado.id === eu.id}
          agir={agir}
          fechar={() => setEditando(null)}
        />
      )}
    </div>
  );
}

type Agir = (acao: () => Promise<unknown>, feito: string) => Promise<boolean>;

function NovoUsuario({ agir }: { agir: Agir }) {
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [perfil, setPerfil] = useState<Perfil>("atendente");
  const [senha, setSenha] = useState("");

  async function criar(evento: FormEvent) {
    evento.preventDefault();
    const ok = await agir(
      () => api.criarUsuario({ nome, email, perfil, senha }),
      `${nome.trim()} cadastrado. Passe a senha para a pessoa por um canal seguro.`,
    );
    if (ok) {
      setNome("");
      setEmail("");
      setPerfil("atendente");
      setSenha("");
    }
  }

  return (
    <form onSubmit={criar} className="form-usuario">
      <h3>Cadastrar</h3>
      <label>
        Nome
        <input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={80} required />
      </label>
      <label>
        E-mail
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="off"
          required
        />
      </label>
      <label>
        Perfil
        <select value={perfil} onChange={(e) => setPerfil(e.target.value as Perfil)}>
          <option value="atendente">Atendente (conversas)</option>
          <option value="gestor">Gestor (tudo, inclusive usuários)</option>
        </select>
      </label>
      <label>
        Senha inicial
        <input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          minLength={SENHA_MINIMA}
          placeholder={`Pelo menos ${SENHA_MINIMA} caracteres`}
          autoComplete="new-password"
          required
        />
      </label>
      <button type="submit">Cadastrar</button>
    </form>
  );
}

function EdicaoUsuario({
  usuario,
  ehVoce,
  agir,
  fechar,
}: {
  usuario: UsuarioGestao;
  ehVoce: boolean;
  agir: Agir;
  fechar: () => void;
}) {
  const [nome, setNome] = useState(usuario.nome);
  const [email, setEmail] = useState(usuario.email);
  const [perfil, setPerfil] = useState<Perfil>(usuario.perfil);
  const [senha, setSenha] = useState("");
  const secao = useRef<HTMLElement>(null);
  const mudou = nome !== usuario.nome || email !== usuario.email || perfil !== usuario.perfil;

  // Abre abaixo da lista: leva o gestor até o painel.
  useEffect(() => secao.current?.scrollIntoView({ behavior: "smooth", block: "start" }), []);

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agir(() => api.editarUsuario(usuario.id, { nome, email, perfil }), "Alterações salvas.");
  }

  async function trocarSenha(evento: FormEvent) {
    evento.preventDefault();
    const ok = await agir(
      () => api.redefinirSenha(usuario.id, senha),
      `Senha de ${usuario.nome} redefinida; as sessões abertas dela foram encerradas.`,
    );
    if (ok) setSenha("");
  }

  return (
    <section ref={secao} className="edicao-usuario" aria-live="polite">
      <h2>Editar {usuario.nome}</h2>

      <form onSubmit={salvar} className="form-usuario">
        <label>
          Nome
          <input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={80} required />
        </label>
        <label>
          E-mail
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Perfil
          <select
            value={perfil}
            onChange={(e) => setPerfil(e.target.value as Perfil)}
            disabled={ehVoce && usuario.perfil === "gestor"}
          >
            <option value="atendente">Atendente (conversas)</option>
            <option value="gestor">Gestor (tudo, inclusive usuários)</option>
          </select>
          {ehVoce && <small>Você não pode tirar o seu próprio perfil de gestor.</small>}
        </label>
        <button type="submit" disabled={!mudou}>
          Salvar
        </button>
      </form>

      <form onSubmit={trocarSenha} className="form-usuario">
        <h3>Redefinir senha</h3>
        <p className="nota">Encerra as sessões abertas da pessoa e desfaz o bloqueio.</p>
        <label>
          Nova senha
          <input
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            minLength={SENHA_MINIMA}
            placeholder={`Pelo menos ${SENHA_MINIMA} caracteres`}
            autoComplete="new-password"
            required
          />
        </label>
        <button type="submit">Redefinir senha</button>
      </form>

      {usuario.situacao === "bloqueado" && (
        <div>
          <h3>Bloqueio</h3>
          <p className="nota">{situacao(usuario)}, depois de 5 senhas erradas.</p>
          <button
            type="button"
            onClick={() => agir(() => api.desbloquearUsuario(usuario.id), `${usuario.nome} desbloqueado.`)}
          >
            Desbloquear agora
          </button>
        </div>
      )}

      <button type="button" onClick={fechar}>
        Fechar
      </button>
    </section>
  );
}
