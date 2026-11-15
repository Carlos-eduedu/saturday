import { type ChangeEvent, type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "../componentes/Avatar";
import { useConfirmar } from "../componentes/Confirmar";
import { Dialogo } from "../componentes/Dialogo";
import { Vazio } from "../componentes/Vazio";
import {
  api,
  enviarFoto,
  type Eu,
  type Perfil,
  mensagemDeFalha,
  type UsuarioGestao,
} from "../api";
import { Falha } from "../componentes/Falha";

// Aba Membros: a seção "Você" (o próprio perfil) para todos e, para o gestor,
// a equipe (decisão 0012): cadastrar, editar, redefinir senha, desbloquear,
// desativar e reativar. Nunca apagar: a auditoria continua dizendo quem fez o
// quê. As travas (não desativar a si mesmo, nunca ficar sem gestor) são da API;
// a tela só esconde o que já sabe que vai ser recusado.

const SENHA_MINIMA = 12;

const ROTULO_PERFIL: Record<Perfil, string> = { atendente: "Atendente", gestor: "Gestor" };

function situacao(u: UsuarioGestao): string {
  if (u.situacao === "bloqueado" && u.bloqueado_ate) {
    const hora = new Date(u.bloqueado_ate).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });
    return `Bloqueado até ${hora}`;
  }
  return u.situacao.charAt(0).toUpperCase() + u.situacao.slice(1);
}

export function Membros({ eu, atualizarEu }: { eu: Eu; atualizarEu: (eu: Eu) => void }) {
  return (
    <div className="canais usuarios">
      <h1 className="titulo-tela">Membros</h1>
      <Voce eu={eu} atualizarEu={atualizarEu} />
      {eu.perfil === "gestor" && <Equipe eu={eu} />}
    </div>
  );
}

// O telefone volta só com dígitos: na tela, com DDD e hífen.
function formatarTelefone(digitos: string | null): string {
  if (!digitos) return "";
  const corpo = digitos.slice(2);
  const meio = corpo.length - 4;
  return `(${digitos.slice(0, 2)}) ${corpo.slice(0, meio)}-${corpo.slice(meio)}`;
}

const FOTO_MAX = 10 * 1024 * 1024;
const FOTO_TIPOS = ["image/jpeg", "image/png", "image/webp"];

// O próprio perfil: nome de exibição, telefone e foto. E-mail e perfil ficam à
// vista, mas só o gestor troca: o e-mail é o login.
function Voce({ eu, atualizarEu }: { eu: Eu; atualizarEu: (eu: Eu) => void }) {
  const [nome, setNome] = useState(eu.nome);
  const [telefone, setTelefone] = useState(formatarTelefone(eu.telefone));
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const arquivo = useRef<HTMLInputElement>(null);
  const mudou = nome.trim() !== eu.nome || telefone.replace(/\D/g, "") !== (eu.telefone ?? "");

  async function executar(acao: () => Promise<Eu>, feito: string) {
    setErro("");
    setAviso("");
    setOcupado(true);
    try {
      const novo = await acao();
      atualizarEu(novo);
      setNome(novo.nome);
      setTelefone(formatarTelefone(novo.telefone));
      setAviso(feito);
    } catch (e) {
      setErro(mensagemDeFalha(e));
    } finally {
      setOcupado(false);
    }
  }

  function escolherFoto(evento: ChangeEvent<HTMLInputElement>) {
    const foto = evento.target.files?.[0];
    evento.target.value = "";
    if (!foto) return;
    if (!FOTO_TIPOS.includes(foto.type)) return setErro("A foto precisa ser JPG, PNG ou WebP.");
    if (foto.size > FOTO_MAX) return setErro("A foto passa de 10 MB. Escolha uma menor.");
    executar(() => enviarFoto(foto), "Foto trocada.");
  }

  return (
    <section className="voce" aria-labelledby="voce-titulo">
      <h2 id="voce-titulo">Você</h2>
      <div className="voce__foto">
        <Avatar nome={eu.nome} foto={eu.foto} tamanho={72} />
        <div className="voce__foto-acoes">
          <button type="button" onClick={() => arquivo.current?.click()} disabled={ocupado}>
            {eu.foto ? "Trocar foto" : "Pôr foto"}
          </button>
          {eu.foto && (
            <button
              type="button"
              className="link"
              onClick={() => executar(api.removerFoto, "Foto removida.")}
              disabled={ocupado}
            >
              Remover
            </button>
          )}
          <span className="nota">JPG, PNG ou WebP, até 10 MB.</span>
        </div>
        <input
          ref={arquivo}
          type="file"
          accept={FOTO_TIPOS.join(",")}
          onChange={escolherFoto}
          hidden
        />
      </div>
      <form
        className="form-usuario"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          executar(() => api.atualizarPerfil(nome.trim(), telefone), "Perfil salvo.");
        }}
      >
        <label>
          Nome de exibição
          <input
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            minLength={2}
            maxLength={80}
            autoComplete="name"
            required
          />
        </label>
        <label>
          Telefone de contato
          <input
            type="tel"
            inputMode="tel"
            value={telefone}
            onChange={(e) => setTelefone(e.target.value)}
            placeholder="DDD e número"
            maxLength={30}
            autoComplete="tel-national"
          />
        </label>
        <dl className="voce__fixos">
          <div>
            <dt>E-mail (login)</dt>
            <dd>{eu.email}</dd>
          </div>
          <div>
            <dt>Perfil</dt>
            <dd>{ROTULO_PERFIL[eu.perfil]}</dd>
          </div>
        </dl>
        <p className="nota">E-mail e perfil só o gestor troca.</p>
        {eu.pode_testar_fluxos && (
          <p className="nota voce__teste">
            {eu.telefone
              ? "Você testa fluxos: as conversas deste telefone no WhatsApp são de teste."
              : "Você testa fluxos: ponha o telefone acima para as suas conversas virarem teste."}
          </p>
        )}
        <button type="submit" disabled={!mudou || ocupado}>
          Salvar
        </button>
      </form>
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
    </section>
  );
}

function Equipe({ eu }: { eu: Eu }) {
  const confirmar = useConfirmar();
  const [usuarios, setUsuarios] = useState<UsuarioGestao[] | null>(null);
  const [erro, setErro] = useState("");
  const [aviso, setAviso] = useState("");
  const [editando, setEditando] = useState<string | null>(null);
  const [adicionando, setAdicionando] = useState(false);

  const carregar = useCallback(() => {
    api
      .gestaoUsuarios()
      .then(setUsuarios)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
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
      setErro(mensagemDeFalha(e));
      return false;
    } finally {
      carregar();
    }
  }

  if (!usuarios)
    return erro ? (
      <Falha titulo="Não deu para carregar os usuários." texto={erro} aoTentar={carregar} />
    ) : (
      <p className="centro">Carregando…</p>
    );
  const selecionado = usuarios.find((u) => u.id === editando) ?? null;

  return (
    <>
      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}
      {aviso && <p className="confere">{aviso}</p>}

      <section>
        <div className="cabeca-secao">
          <h2>Equipe</h2>
          <button type="button" className="principal" onClick={() => setAdicionando(true)}>
            Adicionar usuário
          </button>
        </div>
        {usuarios.length === 0 ? (
          <Vazio titulo="Nenhum usuário." texto="Adicione a primeira pessoa da equipe." />
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
                    <span className="pessoa">
                      <Avatar nome={u.nome} foto={u.foto} tamanho={28} />
                      {u.nome}
                      {u.id === eu.id && <span className="nota"> (você)</span>}
                    </span>
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
                          onClick={async () => {
                            const conversas =
                              u.conversas_assumidas > 0
                                ? ` ${u.conversas_assumidas} conversa(s) assumida(s) por ${u.nome} voltam para "aguardando humano".`
                                : "";
                            const ok = await confirmar({
                              titulo: `Desativar ${u.nome}?`,
                              texto: `A pessoa sai do painel na hora e não entra mais.${conversas}`,
                              acao: "Desativar",
                              perigo: true,
                            });
                            if (!ok) return;
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
      </section>

      {adicionando && (
        <NovoUsuario
          criado={(texto) => {
            setErro("");
            setAviso(texto);
            carregar();
          }}
          fechar={() => setAdicionando(false)}
        />
      )}

      {selecionado && (
        <EdicaoUsuario
          key={selecionado.id}
          usuario={selecionado}
          ehVoce={selecionado.id === eu.id}
          agir={agir}
          fechar={() => setEditando(null)}
        />
      )}
    </>
  );
}

type Agir = (acao: () => Promise<unknown>, feito: string) => Promise<boolean>;

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
  const [editaAgente, setEditaAgente] = useState(usuario.pode_editar_agente);
  const [testaFluxos, setTestaFluxos] = useState(usuario.pode_testar_fluxos);
  const [senha, setSenha] = useState("");
  const secao = useRef<HTMLElement>(null);
  const mudou =
    nome !== usuario.nome ||
    email !== usuario.email ||
    perfil !== usuario.perfil ||
    editaAgente !== usuario.pode_editar_agente ||
    testaFluxos !== usuario.pode_testar_fluxos;

  // Abre abaixo da lista: leva o gestor até o painel.
  useEffect(() => {
    const suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    secao.current?.scrollIntoView({ behavior: suave ? "smooth" : "auto", block: "start" });
  }, []);

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agir(
      () =>
        api.editarUsuario(usuario.id, {
          nome,
          email,
          perfil,
          pode_editar_agente: editaAgente,
          pode_testar_fluxos: testaFluxos,
        }),
      "Alterações salvas.",
    );
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
        <label className="opcao">
          <input
            type="checkbox"
            checked={editaAgente}
            onChange={(e) => setEditaAgente(e.target.checked)}
          />
          Pode editar o agente (modelos, base de conhecimento, voltar versão)
        </label>
        <label className="opcao">
          <input
            type="checkbox"
            checked={testaFluxos}
            onChange={(e) => setTestaFluxos(e.target.checked)}
          />
          Testa fluxos pelo WhatsApp: conversas do telefone do perfil viram teste
          {!usuario.telefone && <small> (a pessoa ainda não pôs telefone no perfil)</small>}
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
