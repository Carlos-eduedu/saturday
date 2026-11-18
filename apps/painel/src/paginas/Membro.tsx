import { type ChangeEvent, type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Avatar } from "../componentes/Avatar";
import { useConfirmar } from "../componentes/Confirmar";
import { EstadoDoMembro } from "../componentes/EstadoDoMembro";
import { Falha } from "../componentes/Falha";
import { api, enviarFoto, type Eu, type Membro, type Perfil, mensagemDeFalha } from "../api";
import { TrocarSenha } from "../componentes/TrocarSenha";
import { conversas, ROTULO_PERFIL, rotuloDaAcao, SENHA_MINIMA } from "../membros";
import { relativo } from "../rotulos";
import { useAcao } from "../useAcao";

// Página do membro (decisão 0023). O servidor manda só o que quem pede pode
// ver: do colega, quem é, o estado e a carga; da própria pessoa e para o
// gestor, também contato, acesso e atividade; só para o gestor, a gestão. As
// travas (não desativar a si mesmo, nunca ficar sem gestor) são da API; a tela
// só esconde o que já sabe que vai ser recusado.

const dataHora = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

type Agir = (acao: () => Promise<unknown>, feito: string) => Promise<boolean>;

export function PaginaDoMembro({ eu, atualizarEu }: { eu: Eu; atualizarEu: (eu: Eu) => void }) {
  const { id = "" } = useParams();
  const [membro, setMembro] = useState<Membro | null>(null);
  const { agir, erro, aviso, setErro, setAviso } = useAcao(() => carregar());

  const carregar = useCallback(() => {
    api
      .membro(id)
      .then(setMembro)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, [id, setErro]);
  useEffect(() => {
    setMembro(null);
    setErro("");
    setAviso("");
    carregar();
  }, [carregar, setErro, setAviso]);

  const voltar = (
    <Link to="/membros" className="membro-voltar">
      <HugeiconsIcon icon={ArrowLeft01Icon} size={18} strokeWidth={2} aria-hidden="true" />
      Membros
    </Link>
  );

  if (!membro)
    return (
      <div className="canais membro">
        {voltar}
        {erro ? (
          <Falha titulo="Não deu para abrir este membro." texto={erro} aoTentar={carregar} />
        ) : (
          <p className="centro">Carregando…</p>
        )}
      </div>
    );

  const desativado = membro.situacao === "desativado";
  const gestor = membro.nivel === "gestor";

  return (
    <div className="canais membro">
      {voltar}
      <header className="membro-cabeca">
        <Avatar nome={membro.nome} foto={membro.foto} tamanho={72} />
        <div className="membro-cabeca__quem">
          <h1 className="titulo-tela">
            {membro.nome}
            {membro.voce && <span className="contagem"> · você</span>}
          </h1>
          <p className="nota">
            {[membro.cargo, ROTULO_PERFIL[membro.perfil]].filter(Boolean).join(" · ")}
          </p>
          {desativado ? (
            <span className="situacao-usuario situacao-desativado">Desativado</span>
          ) : (
            <EstadoDoMembro estado={membro.estado} />
          )}
        </div>
        {membro.voce && (
          <Disponibilidade
            disponivel={eu.disponivel}
            mudar={(disponivel) =>
              agir(
                async () => atualizarEu(await api.marcarDisponibilidade(disponivel)),
                disponivel ? "Você está disponível." : "Você está marcado como ausente.",
              )
            }
          />
        )}
      </header>

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

      <section aria-labelledby="membro-atividade">
        <h2 id="membro-atividade">Atividade</h2>
        <dl className="membro-numeros">
          <div>
            <dt>Assumidas agora</dt>
            <dd className="dado">{conversas(membro.conversas_assumidas)}</dd>
          </div>
          {membro.atividade && (
            <>
              <div>
                <dt>Mensagens enviadas</dt>
                <dd className="dado">{membro.atividade.mensagens}</dd>
              </div>
              <div>
                <dt>Conversas assumidas</dt>
                <dd className="dado">{membro.atividade.assumidas}</dd>
              </div>
              <div>
                <dt>Devolvidas à IA</dt>
                <dd className="dado">{membro.atividade.devolvidas}</dd>
              </div>
              <div>
                <dt>Transferidas</dt>
                <dd className="dado">{membro.atividade.transferidas}</dd>
              </div>
            </>
          )}
        </dl>
        {membro.atividade && (
          <p className="nota">Fora "assumidas agora", os números contam os últimos 7 dias.</p>
        )}
      </section>

      {membro.acoes && (
        <section aria-labelledby="membro-acoes">
          <h2 id="membro-acoes">Últimas ações</h2>
          {membro.acoes.length === 0 ? (
            <p className="nota">Ainda sem ações no painel.</p>
          ) : (
            <ol className="membro-acoes">
              {membro.acoes.map((a, i) => (
                <li key={i}>
                  <span>{rotuloDaAcao(a.acao)}</span>
                  {a.conversa_id && <Link to={`/conversas/${a.conversa_id}`}>Abrir conversa</Link>}
                  <time className="dado" dateTime={a.quando} title={dataHora(a.quando)}>
                    {relativo(a.quando, Date.now())}
                  </time>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      {membro.email !== undefined && (
        <section aria-labelledby="membro-contato">
          <h2 id="membro-contato">Contato e acesso</h2>
          <dl className="voce__fixos">
            <div>
              <dt>E-mail (login)</dt>
              <dd>{membro.email}</dd>
            </div>
            <div>
              <dt>Telefone</dt>
              <dd className={membro.telefone ? "dado" : undefined}>{membro.telefone ?? "Não informado"}</dd>
            </div>
            <div>
              <dt>Último acesso</dt>
              <dd className={membro.ultimo_acesso_em ? "dado" : undefined}>
                {membro.ultimo_acesso_em ? dataHora(membro.ultimo_acesso_em) : "Nunca entrou"}
              </dd>
            </div>
            {membro.criado_em && (
              <div>
                <dt>Cadastro</dt>
                <dd className="dado">{new Date(membro.criado_em).toLocaleDateString("pt-BR")}</dd>
              </div>
            )}
            <div>
              <dt>Permissões</dt>
              <dd>
                {[
                  membro.pode_editar_agente && "Edita o agente",
                  membro.pode_testar_fluxos && "Testa fluxos",
                ]
                  .filter(Boolean)
                  .join(" · ") || "Só as do perfil"}
              </dd>
            </div>
            {gestor && (membro.tentativas_falhas ?? 0) > 0 && (
              <div>
                <dt>Senhas erradas seguidas</dt>
                <dd className="dado">{membro.tentativas_falhas}</dd>
              </div>
            )}
          </dl>
        </section>
      )}

      {membro.voce && <SeuPerfil eu={eu} atualizarEu={atualizarEu} recarregar={carregar} />}

      {gestor && <Gestao key={membro.id} membro={membro} agir={agir} />}
    </div>
  );
}

// A própria pessoa marca. É informação para quem transfere, não bloqueio.
function Disponibilidade({
  disponivel,
  mudar,
}: {
  disponivel: boolean;
  mudar: (disponivel: boolean) => void;
}) {
  return (
    <div className="disponibilidade" role="group" aria-label="Sua disponibilidade">
      <button type="button" aria-pressed={disponivel} onClick={() => disponivel || mudar(true)}>
        Disponível
      </button>
      <button type="button" aria-pressed={!disponivel} onClick={() => disponivel && mudar(false)}>
        Ausente
      </button>
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

// O que a própria pessoa troca: foto, nome de exibição e telefone. E-mail,
// função e perfil só o gestor troca: o e-mail é o login.
function SeuPerfil({
  eu,
  atualizarEu,
  recarregar,
}: {
  eu: Eu;
  atualizarEu: (eu: Eu) => void;
  recarregar: () => void;
}) {
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
      recarregar();
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
      <h2 id="voce-titulo">Seu perfil</h2>
      <div className="voce__foto">
        <Avatar nome={eu.nome} foto={eu.foto} tamanho={56} />
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
        <input ref={arquivo} type="file" accept={FOTO_TIPOS.join(",")} onChange={escolherFoto} hidden />
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
        <p className="nota">E-mail, função e perfil só o gestor troca.</p>
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
      <TrocarSenha
        className="form-usuario"
        email={eu.email}
        cabecalho={
          <>
            <h3 id="senha-titulo">Trocar senha</h3>
            <p className="nota">
              Pelo menos {SENHA_MINIMA} caracteres. As suas outras sessões abertas são encerradas;
              esta continua.
            </p>
          </>
        }
        aoTrocar={recarregar}
      />
    </section>
  );
}

// Só o gestor: cadastro, permissões, senha, bloqueio e desativar (decisão 0012:
// nunca apagar, a auditoria continua dizendo quem fez o quê).
function Gestao({ membro, agir }: { membro: Membro; agir: Agir }) {
  const confirmar = useConfirmar();
  const [nome, setNome] = useState(membro.nome);
  const [email, setEmail] = useState(membro.email ?? "");
  const [cargo, setCargo] = useState(membro.cargo ?? "");
  const [perfil, setPerfil] = useState<Perfil>(membro.perfil);
  const [editaAgente, setEditaAgente] = useState(membro.pode_editar_agente ?? false);
  const [testaFluxos, setTestaFluxos] = useState(membro.pode_testar_fluxos ?? false);
  const [observacao, setObservacao] = useState(membro.observacao ?? "");
  const [senha, setSenha] = useState("");
  const desativado = membro.situacao === "desativado";
  const mudou =
    nome !== membro.nome ||
    email !== (membro.email ?? "") ||
    cargo !== (membro.cargo ?? "") ||
    perfil !== membro.perfil ||
    editaAgente !== (membro.pode_editar_agente ?? false) ||
    testaFluxos !== (membro.pode_testar_fluxos ?? false) ||
    observacao !== (membro.observacao ?? "");

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agir(
      () =>
        api.editarUsuario(membro.id, {
          nome,
          email,
          perfil,
          pode_editar_agente: editaAgente,
          pode_testar_fluxos: testaFluxos,
          cargo,
          observacao,
        }),
      "Alterações salvas.",
    );
  }

  async function trocarSenha(evento: FormEvent) {
    evento.preventDefault();
    const ok = await agir(
      () => api.redefinirSenha(membro.id, senha),
      `Senha de ${membro.nome} redefinida; as sessões abertas dela foram encerradas, e ela escolhe outra ao entrar.`,
    );
    if (ok) setSenha("");
  }

  async function desativar() {
    const voltam =
      membro.conversas_assumidas > 0
        ? ` ${conversas(membro.conversas_assumidas)} de ${membro.nome} ${membro.conversas_assumidas === 1 ? "volta" : "voltam"} para "aguardando humano".`
        : "";
    const ok = await confirmar({
      titulo: `Desativar ${membro.nome}?`,
      texto: `A pessoa sai do painel na hora e não entra mais.${voltam}`,
      acao: "Desativar",
      perigo: true,
    });
    if (ok) agir(() => api.desativarUsuario(membro.id), `${membro.nome} desativado.`);
  }

  return (
    <section className="edicao-usuario" aria-labelledby="membro-gestao">
      <h2 id="membro-gestao">Gestão</h2>

      <form onSubmit={salvar} className="form-usuario">
        {/* O próprio nome a pessoa troca em "Seu perfil", logo acima. */}
        {!membro.voce && (
          <label>
            Nome
            <input value={nome} onChange={(e) => setNome(e.target.value)} maxLength={80} required />
          </label>
        )}
        <label>
          E-mail (login)
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Função
          <input
            value={cargo}
            onChange={(e) => setCargo(e.target.value)}
            maxLength={60}
            placeholder="Ex.: Atendente CLT"
          />
        </label>
        <label>
          Perfil
          <select
            value={perfil}
            onChange={(e) => setPerfil(e.target.value as Perfil)}
            disabled={membro.voce && membro.perfil === "gestor"}
          >
            <option value="atendente">Atendente (conversas)</option>
            <option value="gestor">Gestor (tudo, inclusive usuários)</option>
          </select>
          {membro.voce && <small>Você não pode tirar o seu próprio perfil de gestor.</small>}
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
          {!membro.telefone && <small> (a pessoa ainda não pôs telefone no perfil)</small>}
        </label>
        <label className="largo">
          Observação
          <textarea
            value={observacao}
            onChange={(e) => setObservacao(e.target.value)}
            maxLength={500}
            rows={3}
          />
          <small>Só gestores leem. Não escreva aqui dados de clientes.</small>
        </label>
        <button type="submit" disabled={!mudou}>
          Salvar
        </button>
      </form>

      {/* A própria senha o gestor troca em "Seu perfil", informando a atual; a API recusa aqui. */}
      {!desativado && !membro.voce && (
        <form onSubmit={trocarSenha} className="form-usuario">
          <h3>Redefinir senha</h3>
          <p className="nota">
            Encerra as sessões abertas da pessoa e desfaz o bloqueio. Ela escolhe outra senha ao
            entrar.
          </p>
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
      )}

      {membro.situacao === "bloqueado" && membro.bloqueado_ate && (
        <div>
          <h3>Bloqueio</h3>
          <p className="nota">
            Bloqueado até{" "}
            {new Date(membro.bloqueado_ate).toLocaleTimeString("pt-BR", {
              hour: "2-digit",
              minute: "2-digit",
            })}
            , depois de 5 senhas erradas.
          </p>
          <button
            type="button"
            onClick={() => agir(() => api.desbloquearUsuario(membro.id), `${membro.nome} desbloqueado.`)}
          >
            Desbloquear agora
          </button>
        </div>
      )}

      {desativado ? (
        <div>
          <h3>Reativar</h3>
          <p className="nota">A pessoa volta a entrar com o mesmo e-mail e a mesma senha.</p>
          <button
            type="button"
            onClick={() => agir(() => api.reativarUsuario(membro.id), `${membro.nome} reativado.`)}
          >
            Reativar
          </button>
        </div>
      ) : (
        !membro.voce && (
          <div>
            <h3>Desativar</h3>
            <p className="nota">A pessoa sai do painel e não entra mais. Nada é apagado.</p>
            <button type="button" className="perigo" onClick={desativar}>
              Desativar {membro.nome}
            </button>
          </div>
        )
      )}
    </section>
  );
}
