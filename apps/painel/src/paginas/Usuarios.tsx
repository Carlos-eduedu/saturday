import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { Avatar } from "../componentes/Avatar";
import { Dialogo } from "../componentes/Dialogo";
import { EstadoDoMembro } from "../componentes/EstadoDoMembro";
import { Falha } from "../componentes/Falha";
import { api, type Eu, type Membro, type Perfil, mensagemDeFalha } from "../api";
import { conversas, ROTULO_PERFIL } from "../membros";
import { relativo } from "../rotulos";

// Aba Membros (decisão 0023): a equipe, para todos. Cada linha leva à página do
// membro (`Membro.tsx`), onde ficam os dados e as ações de gestão. O servidor
// decide o que cada um recebe; aqui a linha só desenha o que veio.

const SENHA_MINIMA = 12;

export function Membros({ eu }: { eu: Eu }) {
  const [membros, setMembros] = useState<Membro[] | null>(null);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [adicionando, setAdicionando] = useState(false);
  const gestor = eu.perfil === "gestor";

  const carregar = useCallback(() => {
    api
      .membros()
      .then((lista) => {
        setMembros(lista);
        setErro("");
      })
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, []);
  useEffect(carregar, [carregar]);

  if (!membros)
    return erro ? (
      <Falha titulo="Não deu para carregar a equipe." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );

  // Você primeiro; o resto na ordem do servidor (por nome).
  const ativos = membros
    .filter((m) => m.situacao !== "desativado")
    .sort((a, b) => Number(b.voce) - Number(a.voce));
  const desativados = membros.filter((m) => m.situacao === "desativado");

  return (
    <div className="canais membros">
      <div className="cabeca-secao">
        <h1 className="titulo-tela">
          Membros <span className="contagem">· {ativos.length}</span>
        </h1>
        {gestor && (
          <button type="button" className="principal" onClick={() => setAdicionando(true)}>
            Adicionar usuário
          </button>
        )}
      </div>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && (
        <p className="confere" role="status">
          {aviso}
        </p>
      )}

      <section aria-label="Equipe">
        <ul className="membros-lista">
          {ativos.map((m) => (
            <Linha key={m.id} membro={m} />
          ))}
        </ul>
      </section>

      {desativados.length > 0 && (
        <section aria-labelledby="membros-desativados">
          <h2 id="membros-desativados">Desativados</h2>
          <p className="nota">Não entram no painel. A linha fica para a auditoria dizer quem fez o quê.</p>
          <ul className="membros-lista">
            {desativados.map((m) => (
              <Linha key={m.id} membro={m} />
            ))}
          </ul>
        </section>
      )}

      {adicionando && (
        <NovoUsuario
          criado={(texto) => {
            setAviso(texto);
            carregar();
          }}
          fechar={() => setAdicionando(false)}
        />
      )}
    </div>
  );
}

function Linha({ membro: m }: { membro: Membro }) {
  const desativado = m.situacao === "desativado";
  return (
    <li>
      <Link to={`/membros/${m.id}`} className="membro-linha" data-desativado={desativado || undefined}>
        <Avatar nome={m.nome} foto={m.foto} tamanho={40} />
        <span className="membro-linha__quem">
          <span className="membro-linha__nome">
            {m.nome}
            {m.voce && <span className="nota"> (você)</span>}
          </span>
          <span className="nota">
            {[m.cargo, ROTULO_PERFIL[m.perfil]].filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="membro-linha__estado">
          {desativado ? (
            <span className="nota">Desativado</span>
          ) : (
            <EstadoDoMembro estado={m.estado} />
          )}
          {m.situacao === "bloqueado" && <span className="situacao-bloqueado">Bloqueado</span>}
        </span>
        {!desativado && (
          <span className="membro-linha__carga">
            <span className="dado">{conversas(m.conversas_assumidas)}</span>
            {m.nivel === "gestor" && (
              <span className="nota">
                {m.ultimo_acesso_em
                  ? `visto ${relativo(m.ultimo_acesso_em, Date.now())}`
                  : "nunca entrou"}
              </span>
            )}
          </span>
        )}
      </Link>
    </li>
  );
}

// Adicionar abre num diálogo: preencher, conferir e confirmar.
function NovoUsuario({ criado, fechar }: { criado: (aviso: string) => void; fechar: () => void }) {
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [perfil, setPerfil] = useState<Perfil>("atendente");
  const [senha, setSenha] = useState("");
  // A falha fica no diálogo, onde a pessoa está olhando.
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function criar(evento: FormEvent) {
    evento.preventDefault();
    setErro("");
    setEnviando(true);
    try {
      await api.criarUsuario({ nome, email, perfil, senha });
      criado(`${nome.trim()} adicionado. Passe a senha para a pessoa por um canal seguro.`);
      fechar();
    } catch (e) {
      setErro(mensagemDeFalha(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Dialogo
      titulo="Adicionar usuário"
      aoFechar={fechar}
      rodape={
        <>
          <button type="button" onClick={fechar}>
            Cancelar
          </button>
          <button type="submit" form="novo-usuario" className="principal" disabled={enviando}>
            {enviando ? "Adicionando…" : "Adicionar"}
          </button>
        </>
      }
    >
    <form id="novo-usuario" onSubmit={criar} className="form-usuario">
      <p className="nota">
        A pessoa entra com este e-mail e a senha inicial. Passe a senha por um canal seguro.
      </p>
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
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
    </form>
    </Dialogo>
  );
}
