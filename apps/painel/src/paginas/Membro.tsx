import { type ChangeEvent, type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import {
  ArrowLeft01Icon,
  SecurityLockIcon,
  UserEdit01Icon,
  ViewIcon,
  ViewOffIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { Avatar } from "../componentes/Avatar";
import { useConfirmar } from "../componentes/Confirmar";
import { Dialogo } from "../componentes/Dialogo";
import { EstadoDoMembro } from "../componentes/EstadoDoMembro";
import { Falha } from "../componentes/Falha";
import { Notificacao } from "../componentes/Notificacao";
import { api, enviarFoto, type Eu, type Membro, type Perfil, mensagemDeFalha } from "../api";
import { TrocarSenha } from "../componentes/TrocarSenha";
import { conversas, ROTULO_PERFIL, rotuloDaAcao, SENHA_MINIMA } from "../membros";
import { relativo } from "../rotulos";
import { useAcao } from "../useAcao";

// Página do membro (decisão 0023). O servidor manda só o que quem pede pode
// ver: do colega, quem é, o estado e a carga; da própria pessoa e para o
// gestor, também contato, acesso e atividade; só para o gestor, a gestão. As
// travas (não desativar a si mesmo, nunca ficar sem gestor) são da API; a tela
// só esconde o que já sabe que vai ser recusado. Ver e editar ficam em dois
// modais (Perfil e Acesso); a página guarda a atividade e o que é irreversível.

const dataHora = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  });

type Agir = (acao: () => Promise<unknown>, feito: string) => Promise<boolean>;
type Modal = "perfil" | "senha" | "acesso" | "redefinir" | null;

export function PaginaDoMembro({ eu, atualizarEu }: { eu: Eu; atualizarEu: (eu: Eu) => void }) {
  const { id = "" } = useParams();
  const [membro, setMembro] = useState<Membro | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const confirmar = useConfirmar();
  const { agir, erro, aviso, setErro, setAviso } = useAcao(() => carregar());
  const fecharAviso = useCallback(() => setAviso(""), [setAviso]);

  const carregar = useCallback(() => {
    api
      .membro(id)
      .then(setMembro)
      .catch((e: unknown) => setErro(mensagemDeFalha(e)));
  }, [id, setErro]);
  useEffect(() => {
    setMembro(null);
    setModal(null);
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
  // Contato e acesso vêm só para a própria pessoa e para o gestor.
  const ve = membro.email !== undefined;
  const semMascara = membro.ve_dados_completos ?? false;
  // Ação feita dentro de um modal: deu certo, ele fecha e o aviso sai em notificação.
  const agirEFechar: Agir = async (acao, feito) => {
    const ok = await agir(acao, feito);
    if (ok) setModal(null);
    return ok;
  };

  async function alternarMascara(m: Membro) {
    const ligar = !semMascara;
    const ok = await confirmar(
      ligar
        ? {
            titulo: `Mostrar dados sem máscara para ${m.nome}?`,
            texto: `${m.voce ? "Você passa" : `${m.nome} passa`} a ver CPF, telefone, e-mail e nascimento inteiros em todo o painel. Cada ficha de cliente aberta assim fica na auditoria. A exportação continua mascarada.`,
            acao: "Mostrar sem máscara",
          }
        : {
            titulo: `Voltar a mascarar os dados para ${m.nome}?`,
            texto: "Os dados pessoais voltam a aparecer mascarados, com o Revelar auditado.",
            acao: "Mascarar",
          },
    );
    if (!ok) return;
    agir(
      async () => {
        await api.editarUsuario(m.id, { ve_dados_completos: ligar });
        if (m.voce) atualizarEu(await api.eu());
      },
      ligar ? `${m.nome} vê os dados sem máscara.` : `Os dados voltam mascarados para ${m.nome}.`,
    );
  }

  // Com um modal aberto, a recusa aparece nele: a página fica atrás do fundo.
  const erroNoModal = erro && (
    <p className="erro" role="alert">
      {erro}
    </p>
  );

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

      {ve && (
        <div className="membro-botoes">
          <button type="button" onClick={() => setModal("perfil")}>
            <HugeiconsIcon icon={UserEdit01Icon} size={18} strokeWidth={2} aria-hidden="true" />
            Perfil
          </button>
          <button type="button" onClick={() => setModal("acesso")}>
            <HugeiconsIcon icon={SecurityLockIcon} size={18} strokeWidth={2} aria-hidden="true" />
            Acesso
          </button>
          {gestor && (
            <button
              type="button"
              className="membro-mascara"
              aria-pressed={semMascara}
              onClick={() => alternarMascara(membro)}
            >
              <HugeiconsIcon
                icon={semMascara ? ViewIcon : ViewOffIcon}
                size={18}
                strokeWidth={2}
                aria-hidden="true"
              />
              Dados sem máscara
              <span className="membro-mascara__estado">{semMascara ? "ligado" : "desligado"}</span>
            </button>
          )}
        </div>
      )}

      {!modal && erroNoModal}
      {aviso && <Notificacao texto={aviso} aoFechar={fecharAviso} />}

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

      {gestor && <Situacao membro={membro} agir={agir} />}

      {modal === "perfil" && (
        <Dialogo
          titulo={membro.voce ? "Seu perfil" : `Perfil de ${membro.nome}`}
          aoFechar={() => setModal(null)}
        >
          {erroNoModal}
          <Fixos membro={membro} gestor={gestor} />
          <Perfil
            membro={membro}
            eu={eu}
            gestor={gestor}
            atualizarEu={atualizarEu}
            agir={agir}
            agirEFechar={agirEFechar}
            trocarSenha={() => setModal("senha")}
          />
        </Dialogo>
      )}
      {modal === "redefinir" && (
        <Dialogo titulo={`Redefinir a senha de ${membro.nome}`} aoFechar={() => setModal(null)}>
          {erroNoModal}
          <RedefinirSenha membro={membro} agir={agirEFechar} />
        </Dialogo>
      )}
      {modal === "senha" && (
        <Dialogo titulo="Trocar senha" aoFechar={() => setModal(null)}>
          <TrocarSenha
            className="form-usuario"
            email={eu.email}
            cabecalho={
              <p className="nota">
                Pelo menos {SENHA_MINIMA} caracteres. As suas outras sessões abertas são
                encerradas; esta continua.
              </p>
            }
            aoTrocar={() => {
              setModal(null);
              setAviso("Senha trocada. As suas outras sessões foram encerradas.");
              carregar();
            }}
          />
        </Dialogo>
      )}
      {modal === "acesso" && (
        <Dialogo
          titulo={membro.voce ? "Seu acesso" : `Acesso de ${membro.nome}`}
          aoFechar={() => setModal(null)}
        >
          {erroNoModal}
          {gestor ? (
            <Acesso
              membro={membro}
              agir={agir}
              agirEFechar={agirEFechar}
              redefinirSenha={() => setModal("redefinir")}
            />
          ) : (
            <Permissoes membro={membro} />
          )}
        </Dialogo>
      )}
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

// Um formulário, um Salvar: a própria pessoa troca nome de exibição e
// telefone (`/eu`); o gestor troca nome, e-mail (o login), função e
// observação (`/gestao/usuarios`). O que mudou vai para a rota de quem pode.
// A foto troca na hora, fora do Salvar; a senha tem modal próprio.
function Perfil({
  membro,
  eu,
  gestor,
  atualizarEu,
  agir,
  agirEFechar,
  trocarSenha,
}: {
  membro: Membro;
  eu: Eu;
  gestor: boolean;
  atualizarEu: (eu: Eu) => void;
  agir: Agir;
  agirEFechar: Agir;
  trocarSenha: () => void;
}) {
  const voce = membro.voce;
  const [nome, setNome] = useState(voce ? eu.nome : membro.nome);
  const [telefone, setTelefone] = useState(formatarTelefone(eu.telefone));
  const [email, setEmail] = useState(membro.email ?? "");
  const [cargo, setCargo] = useState(membro.cargo ?? "");
  const [observacao, setObservacao] = useState(membro.observacao ?? "");
  const [erroFoto, setErroFoto] = useState("");
  const arquivo = useRef<HTMLInputElement>(null);

  const mudouProprio =
    voce && (nome.trim() !== eu.nome || telefone.replace(/\D/g, "") !== (eu.telefone ?? ""));
  const mudouCadastro =
    gestor &&
    ((!voce && nome !== membro.nome) ||
      email !== (membro.email ?? "") ||
      cargo !== (membro.cargo ?? "") ||
      observacao !== (membro.observacao ?? ""));

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agirEFechar(async () => {
      if (mudouProprio) atualizarEu(await api.atualizarPerfil(nome.trim(), telefone));
      if (mudouCadastro)
        await api.editarUsuario(membro.id, {
          ...(voce ? {} : { nome }),
          email,
          cargo,
          observacao,
        });
    }, "Perfil salvo.");
  }

  function escolherFoto(evento: ChangeEvent<HTMLInputElement>) {
    const foto = evento.target.files?.[0];
    evento.target.value = "";
    setErroFoto("");
    if (!foto) return;
    if (!FOTO_TIPOS.includes(foto.type)) return setErroFoto("A foto precisa ser JPG, PNG ou WebP.");
    if (foto.size > FOTO_MAX) return setErroFoto("A foto passa de 10 MB. Escolha uma menor.");
    agir(async () => atualizarEu(await enviarFoto(foto)), "Foto trocada.");
  }

  return (
    <>
      {voce && (
        <div className="voce__foto">
          <Avatar nome={eu.nome} foto={eu.foto} tamanho={56} />
          <div className="voce__foto-acoes">
            <button type="button" onClick={() => arquivo.current?.click()}>
              {eu.foto ? "Trocar foto" : "Pôr foto"}
            </button>
            {eu.foto && (
              <button
                type="button"
                className="link"
                onClick={() => agir(async () => atualizarEu(await api.removerFoto()), "Foto removida.")}
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
      )}
      {erroFoto && (
        <p className="erro" role="alert">
          {erroFoto}
        </p>
      )}
      <form className="form-usuario" onSubmit={salvar}>
        <label>
          {voce ? "Nome de exibição" : "Nome"}
          <input
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            minLength={2}
            maxLength={80}
            autoComplete={voce ? "name" : "off"}
            required
          />
        </label>
        {voce && (
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
        )}
        {gestor && (
          <>
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
          </>
        )}
        {!gestor && <p className="nota">E-mail, função e perfil só o gestor troca.</p>}
        {voce && eu.pode_testar_fluxos && (
          <p className="nota voce__teste">
            {eu.telefone
              ? "Você testa fluxos: as conversas deste telefone no WhatsApp são de teste."
              : "Você testa fluxos: ponha o telefone acima para as suas conversas virarem teste."}
          </p>
        )}
        <div className="membro-form-acoes">
          <button type="submit" disabled={!mudouProprio && !mudouCadastro}>
            Salvar
          </button>
          {voce && (
            <button type="button" onClick={trocarSenha}>
              Trocar senha
            </button>
          )}
        </div>
      </form>
    </>
  );
}

const PERMISSOES: [keyof Membro, string][] = [
  ["pode_editar_agente", "Edita o agente"],
  ["pode_testar_fluxos", "Testa fluxos"],
  ["ve_dados_completos", "Vê dados sem máscara"],
];

// O que ninguém edita neste modal: quando entrou, quando apareceu, e o que só
// outra pessoa troca (o telefone é do próprio membro; o e-mail, do gestor).
function Fixos({ membro, gestor }: { membro: Membro; gestor: boolean }) {
  return (
    <dl className="voce__fixos membro-fixos">
      {!gestor && (
        <div>
          <dt>E-mail (login)</dt>
          <dd>{membro.email}</dd>
        </div>
      )}
      {!membro.voce && (
        <div>
          <dt>Telefone</dt>
          <dd className={membro.telefone ? "dado" : undefined}>
            {membro.telefone ?? "Não informado"}
          </dd>
        </div>
      )}
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
    </dl>
  );
}

// A própria pessoa (atendente) vê o acesso, sem mexer: só o gestor troca.
function Permissoes({ membro }: { membro: Membro }) {
  const ligadas = PERMISSOES.filter(([campo]) => membro[campo]).map(([, rotulo]) => rotulo);
  return (
    <>
      <dl className="voce__fixos">
        <div>
          <dt>Perfil</dt>
          <dd>{ROTULO_PERFIL[membro.perfil]}</dd>
        </div>
        <div>
          <dt>Permissões</dt>
          <dd>{ligadas.join(" · ") || "Só as do perfil"}</dd>
        </div>
      </dl>
      <p className="nota">Perfil e permissões só o gestor troca.</p>
    </>
  );
}

// Só o gestor: perfil, permissões, senha e bloqueio.
function Acesso({
  membro,
  agir,
  agirEFechar,
  redefinirSenha,
}: {
  membro: Membro;
  agir: Agir;
  agirEFechar: Agir;
  redefinirSenha: () => void;
}) {
  const [perfil, setPerfil] = useState<Perfil>(membro.perfil);
  const [editaAgente, setEditaAgente] = useState(membro.pode_editar_agente ?? false);
  const [testaFluxos, setTestaFluxos] = useState(membro.pode_testar_fluxos ?? false);
  const desativado = membro.situacao === "desativado";
  const mudou =
    perfil !== membro.perfil ||
    editaAgente !== (membro.pode_editar_agente ?? false) ||
    testaFluxos !== (membro.pode_testar_fluxos ?? false);

  function salvar(evento: FormEvent) {
    evento.preventDefault();
    agirEFechar(
      () =>
        api.editarUsuario(membro.id, {
          perfil,
          pode_editar_agente: editaAgente,
          pode_testar_fluxos: testaFluxos,
        }),
      "Acesso salvo.",
    );
  }

  return (
    <>
      <form onSubmit={salvar} className="form-usuario membro-form-acesso">
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
        <label className="opcao largo">
          <input
            type="checkbox"
            checked={editaAgente}
            onChange={(e) => setEditaAgente(e.target.checked)}
          />
          Pode editar o agente (modelos, base de conhecimento, voltar versão)
        </label>
        <label className="opcao largo">
          <input
            type="checkbox"
            checked={testaFluxos}
            onChange={(e) => setTestaFluxos(e.target.checked)}
          />
          Testa fluxos pelo WhatsApp: conversas do telefone do perfil viram teste
          {!membro.telefone && <small> (a pessoa ainda não pôs telefone no perfil)</small>}
        </label>
        <p className="nota">
          Dados sem máscara se liga no botão da página, com confirmação: hoje está{" "}
          {membro.ve_dados_completos ? "ligado" : "desligado"}.
        </p>
        {membro.trocar_senha && (
          <p className="nota situacao-pendente">
            Troca de senha pendente: a pessoa ainda não trocou a senha definida pelo gestor.
          </p>
        )}
        <div className="membro-form-acoes">
          <button type="submit" disabled={!mudou}>
            Salvar acesso
          </button>
          {/* A própria senha o gestor troca em "Seu perfil", informando a atual; a API recusa aqui. */}
          {!desativado && !membro.voce && (
            <button type="button" onClick={redefinirSenha}>
              Redefinir senha
            </button>
          )}
        </div>
      </form>

      {membro.situacao === "bloqueado" && membro.bloqueado_ate && (
        <div className="membro-bloco">
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
            onClick={() =>
              agir(() => api.desbloquearUsuario(membro.id), `${membro.nome} desbloqueado.`)
            }
          >
            Desbloquear agora
          </button>
        </div>
      )}
    </>
  );
}

// Só o gestor, para outra pessoa: a senha nova encerra as sessões dela.
function RedefinirSenha({ membro, agir }: { membro: Membro; agir: Agir }) {
  const [senha, setSenha] = useState("");
  return (
    <form
      className="form-usuario"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        agir(
          () => api.redefinirSenha(membro.id, senha),
          `Senha de ${membro.nome} redefinida; as sessões abertas dela foram encerradas, e ela escolhe outra ao entrar.`,
        );
      }}
    >
      <p className="nota">
        Encerra as sessões abertas da pessoa e desfaz o bloqueio. Ela escolhe outra senha ao entrar.
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
  );
}

// Só o gestor, fora dos modais: desativar e reativar (decisão 0012: nunca
// apagar, a auditoria continua dizendo quem fez o quê).
function Situacao({ membro, agir }: { membro: Membro; agir: Agir }) {
  const confirmar = useConfirmar();
  const desativado = membro.situacao === "desativado";
  if (membro.voce && !desativado) return null;

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
    <section className="membro-situacao" aria-labelledby="membro-situacao">
      {desativado ? (
        <>
          <div>
            <h2 id="membro-situacao">Reativar</h2>
            <p className="nota">A pessoa volta a entrar com o mesmo e-mail e a mesma senha.</p>
          </div>
          <button
            type="button"
            onClick={() => agir(() => api.reativarUsuario(membro.id), `${membro.nome} reativado.`)}
          >
            Reativar
          </button>
        </>
      ) : (
        <>
          <div>
            <h2 id="membro-situacao">Desativar</h2>
            <p className="nota">A pessoa sai do painel e não entra mais. Nada é apagado.</p>
          </div>
          <button type="button" className="perigo" onClick={desativar}>
            Desativar {membro.nome}
          </button>
        </>
      )}
    </section>
  );
}
