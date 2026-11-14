import {
  Attachment01Icon,
  Cancel01Icon,
  Delete02Icon,
  Download04Icon,
  Pdf01Icon,
  StopIcon,
  FlashIcon,
  Mail01Icon,
  Mic01Icon,
  PlusSignIcon,
  SentIcon,
  UserEdit01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ANEXOS_ACEITOS,
  api,
  type ContaNova,
  type Detalhe,
  type EdicaoFicha,
  type Eu,
  exportarUrl,
  type Ficha,
  enviarAnexo,
  type RespostaRapida,
} from "../api";
import { MODELOS, rotulo } from "../rotulos";
import { type Banco, CamposConta, CONTA_VAZIA } from "./CamposConta";
import { Dialogo } from "./Dialogo";
import { LIMITE_GRAVACAO_S, useGravador } from "./useGravador";

type Agir = (acao: () => Promise<unknown>) => Promise<void>;
type Aberto = "ficha" | "modelo" | null;

const ALTURA_MAXIMA = 220; // ~8 linhas; depois disso o campo rola.
const MB = 1024 * 1024;

const tamanho = (bytes: number) =>
  bytes >= MB
    ? `${(bytes / MB).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

const relogio = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

// Área de escrever da conversa: campo que cresce, respostas rápidas com "/",
// atalhos do painel (ficha, modelo, exportar), anexo (botão ou arrastar) e
// áudio gravado. O texto do campo vira a legenda do anexo.
// Só quem assumiu escreve; o gestor também corrige a ficha sem assumir.
export function Compositor({
  conversa,
  eu,
  minha,
  focar,
  agir,
  assumir,
}: {
  conversa: Detalhe;
  eu: Eu;
  minha: boolean;
  focar: boolean;
  agir: Agir;
  // Presente quando quem vê pode assumir: o botão fica onde o polegar já está,
  // e no celular o cabeçalho com o Assumir rola para longe.
  assumir?: { acao: () => void; ocupado: boolean };
}) {
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [aberto, setAberto] = useState<Aberto>(null);
  const [respostas, setRespostas] = useState<RespostaRapida[]>([]);
  const [indice, setIndice] = useState(0);
  const [semSugestoes, setSemSugestoes] = useState(false);
  const [anexo, setAnexo] = useState<{ arquivo: File; url: string } | null>(null);
  const [erroAnexo, setErroAnexo] = useState("");
  const [arrastando, setArrastando] = useState(false);
  const campo = useRef<HTMLTextAreaElement>(null);
  const seletor = useRef<HTMLInputElement>(null);
  const gravador = useGravador(escolherArquivo);

  // A prévia (imagem, player) usa um object URL: solto quando o anexo sai.
  useEffect(
    () => () => {
      if (anexo) URL.revokeObjectURL(anexo.url);
    },
    [anexo],
  );

  useEffect(() => {
    api
      .respostas()
      .then(setRespostas)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (focar && minha) campo.current?.focus();
  }, [focar, minha]);
  useLayoutEffect(() => {
    const el = campo.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, ALTURA_MAXIMA)}px`;
  }, [texto]);

  // Evolution não tem janela nem modelo: sempre texto (decisão 0009).
  const meta = conversa.canal === "whatsapp";
  const janelaAberta = conversa.janela_aberta || !meta;
  const temModelo = meta && conversa.modelos.length > 0;
  const podeFicha = minha || eu.perfil === "gestor";
  const podeAnexar = minha && janelaAberta && !enviando && !gravador.gravando;
  const audio = anexo?.arquivo.type.startsWith("audio/") ?? false;

  function escolherArquivo(arquivo: File) {
    const limite = ANEXOS_ACEITOS[arquivo.type.split(";")[0]];
    if (!limite) {
      setErroAnexo("Tipo não aceito: envie JPG, PNG, PDF ou áudio.");
      return;
    }
    if (arquivo.size > limite) {
      setErroAnexo(`${arquivo.name} tem ${tamanho(arquivo.size)}; o limite é ${limite / MB} MB.`);
      return;
    }
    setErroAnexo("");
    setAnexo({ arquivo, url: URL.createObjectURL(arquivo) });
  }

  const busca = /^\/(\S*)$/.exec(texto)?.[1]?.toLowerCase();
  const sugestoes =
    busca === undefined || semSugestoes
      ? []
      : respostas
          .filter((r) => r.atalho.startsWith(busca) || r.texto.toLowerCase().includes(busca))
          .slice(0, 6);
  const ativa = Math.min(indice, Math.max(sugestoes.length - 1, 0));

  function escolher(r: RespostaRapida) {
    setTexto(r.texto);
    setIndice(0);
    campo.current?.focus();
  }

  async function enviar(evento?: FormEvent) {
    evento?.preventDefault();
    if ((!texto.trim() && !anexo) || enviando || !minha) return;
    setEnviando(true);
    await agir(async () => {
      if (anexo) {
        await enviarAnexo(conversa.id, anexo.arquivo, anexo.arquivo.name, audio ? "" : texto.trim());
        setAnexo(null);
        if (!audio) setTexto("");
      } else {
        await api.enviar(conversa.id, { texto });
        setTexto("");
      }
    });
    setEnviando(false);
  }

  function teclas(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (sugestoes.length > 0) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const passo = e.key === "ArrowDown" ? 1 : -1;
        setIndice((ativa + passo + sugestoes.length) % sugestoes.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        escolher(sugestoes[ativa]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSemSugestoes(true);
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void enviar();
    }
  }

  const placeholder = minha
    ? anexo
      ? "Legenda (opcional)"
      : respostas.length > 0
      ? "Escreva a mensagem ou / para uma resposta rápida"
      : "Escreva a mensagem"
    : assumir
    ? "Assuma a conversa para responder"
    : "Só quem está com a conversa responde";

  return (
    <div className="envio">
      {!janelaAberta && minha && (
        <p className="aviso">Janela de 24 h fechada: só é possível enviar um modelo.</p>
      )}
      <form
        className={["compositor", !minha && "inativo", arrastando && "arrastando"].filter(Boolean).join(" ")}
        onSubmit={enviar}
        onDragOver={(e) => {
          if (!podeAnexar || !e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          setArrastando(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setArrastando(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setArrastando(false);
          const arquivo = e.dataTransfer.files[0];
          if (arquivo && podeAnexar) escolherArquivo(arquivo);
        }}
      >
        <input
          ref={seletor}
          type="file"
          hidden
          accept={Object.keys(ANEXOS_ACEITOS).join(",")}
          onChange={(e) => {
            const arquivo = e.target.files?.[0];
            if (arquivo) escolherArquivo(arquivo);
            e.target.value = "";
          }}
        />
        {sugestoes.length > 0 && (
          <ul className="sugestoes" role="listbox" id="respostas-rapidas" aria-label="Respostas rápidas">
            {sugestoes.map((r, i) => (
              <li
                key={r.id}
                role="option"
                aria-selected={i === ativa}
                onMouseDown={(e) => {
                  e.preventDefault();
                  escolher(r);
                }}
              >
                <code>/{r.atalho}</code>
                <span>{r.texto}</span>
              </li>
            ))}
          </ul>
        )}
        {(anexo || erroAnexo || gravador.erro) && (
          <div className="anexo-pendente">
            {anexo && (
              <div className="chip-anexo">
                {audio ? (
                  <audio controls src={anexo.url} aria-label="Ouvir o áudio gravado" />
                ) : anexo.arquivo.type.startsWith("image/") ? (
                  <img src={anexo.url} alt="" />
                ) : (
                  <HugeiconsIcon icon={Pdf01Icon} size={22} strokeWidth={1.8} />
                )}
                {!audio && (
                  <span className="dados-anexo">
                    <span className="nome">{anexo.arquivo.name}</span>
                    <small>{tamanho(anexo.arquivo.size)}</small>
                  </span>
                )}
                <button
                  type="button"
                  className="icone"
                  onClick={() => setAnexo(null)}
                  aria-label={audio ? "Remover o áudio" : "Remover o anexo"}
                  title="Remover"
                >
                  <HugeiconsIcon icon={audio ? Delete02Icon : Cancel01Icon} size={18} strokeWidth={2} />
                </button>
              </div>
            )}
            {(erroAnexo || gravador.erro) && (
              <p className="erro" role="alert">
                {erroAnexo || gravador.erro}
              </p>
            )}
          </div>
        )}
        {gravador.gravando && (
          <div className="gravando" role="status">
            <span className="ponto" aria-hidden="true" />
            Gravando <time>{relogio(gravador.segundos)}</time>
            <small>até {relogio(LIMITE_GRAVACAO_S)}</small>
          </div>
        )}
        {janelaAberta && !gravador.gravando && !audio && (
          <textarea
            ref={campo}
            value={texto}
            onChange={(e) => {
              setTexto(e.target.value);
              setSemSugestoes(false);
            }}
            onKeyDown={teclas}
            rows={1}
            disabled={!minha}
            placeholder={placeholder}
            aria-label="Mensagem"
            aria-controls={sugestoes.length > 0 ? "respostas-rapidas" : undefined}
            aria-expanded={sugestoes.length > 0}
            aria-autocomplete="list"
          />
        )}
        <div className="barra">
          <MenuAtalhos
            itens={[
              {
                rotulo: "Editar ficha",
                icone: UserEdit01Icon,
                desabilitado: !podeFicha,
                agir: () => setAberto("ficha"),
              },
              {
                rotulo: "Respostas rápidas",
                icone: FlashIcon,
                desabilitado: !minha || !janelaAberta || respostas.length === 0,
                agir: () => {
                  setTexto("/");
                  setSemSugestoes(false);
                  requestAnimationFrame(() => campo.current?.focus());
                },
              },
              ...(temModelo
                ? [
                    {
                      rotulo: "Enviar modelo",
                      icone: Mail01Icon,
                      desabilitado: !minha,
                      agir: () => setAberto("modelo"),
                    },
                  ]
                : []),
              { rotulo: "Exportar conversa (.md)", icone: Download04Icon, href: exportarUrl(conversa.id) },
            ]}
          />
          <button
            type="button"
            className="icone"
            disabled={!podeAnexar}
            onClick={() => seletor.current?.click()}
            aria-label="Anexar arquivo"
            title="Anexar JPG, PNG ou PDF (ou arraste aqui)"
          >
            <HugeiconsIcon icon={Attachment01Icon} size={20} strokeWidth={2} />
          </button>
          <button
            type="button"
            className="icone"
            disabled={!podeAnexar || !!anexo || !gravador.suportado}
            onClick={() => void gravador.iniciar()}
            aria-label="Gravar áudio"
            title={gravador.suportado ? "Gravar áudio" : "Este navegador não grava áudio"}
          >
            <HugeiconsIcon icon={Mic01Icon} size={20} strokeWidth={2} />
          </button>
          {gravador.gravando ? (
            <>
              <button type="button" className="cancelar-gravacao" onClick={gravador.cancelar}>
                Cancelar
              </button>
              <button type="button" className="principal enviar" onClick={gravador.parar}>
                <HugeiconsIcon icon={StopIcon} size={18} strokeWidth={2} />
                Parar
              </button>
            </>
          ) : !minha && assumir ? (
            <button
              type="button"
              className="principal enviar"
              disabled={assumir.ocupado}
              onClick={assumir.acao}
            >
              Assumir para responder
            </button>
          ) : janelaAberta ? (
            <>
              {minha && (
                <span className="dica" aria-hidden="true">
                  Ctrl ou ⌘ + Enter envia
                </span>
              )}
              <button
                type="submit"
                className="enviar"
                disabled={!minha || enviando || (!texto.trim() && !anexo)}
              >
                <HugeiconsIcon icon={SentIcon} size={18} strokeWidth={2} />
                {enviando ? "Enviando…" : "Enviar"}
              </button>
            </>
          ) : (
            temModelo && (
              <button
                type="button"
                className="principal enviar"
                disabled={!minha}
                onClick={() => setAberto("modelo")}
              >
                <HugeiconsIcon icon={Mail01Icon} size={18} strokeWidth={2} />
                Enviar modelo
              </button>
            )
          )}
        </div>
      </form>
      {aberto === "ficha" && (
        <EditarFicha conversaId={conversa.id} aoFechar={() => setAberto(null)} agir={agir} />
      )}
      {aberto === "modelo" && (
        <EnviarModelo conversa={conversa} aoFechar={() => setAberto(null)} agir={agir} />
      )}
    </div>
  );
}

type ItemMenu = {
  rotulo: string;
  icone: typeof FlashIcon;
  desabilitado?: boolean;
  agir?: () => void;
  href?: string;
};

// Menu que abre para cima, sobre o campo. `details` dá o abre e fecha sem
// estado; Esc e o clique num item fecham.
function MenuAtalhos({ itens }: { itens: ItemMenu[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const fechar = () => {
    if (ref.current) ref.current.open = false;
  };
  useEffect(() => {
    const fora = (e: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) fechar();
    };
    document.addEventListener("click", fora);
    return () => document.removeEventListener("click", fora);
  }, []);

  return (
    <details
      ref={ref}
      className="menu-atalhos"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          fechar();
          ref.current?.querySelector("summary")?.focus();
        }
      }}
    >
      <summary aria-label="Atalhos" title="Atalhos">
        <HugeiconsIcon icon={PlusSignIcon} size={20} strokeWidth={2} />
      </summary>
      <div className="menu-atalhos__painel" role="menu">
        {itens.map((item) =>
          item.href ? (
            <a key={item.rotulo} role="menuitem" href={item.href} onClick={fechar}>
              <HugeiconsIcon icon={item.icone} size={18} strokeWidth={2} />
              {item.rotulo}
            </a>
          ) : (
            <button
              key={item.rotulo}
              type="button"
              role="menuitem"
              disabled={item.desabilitado}
              onClick={() => {
                fechar();
                item.agir?.();
              }}
            >
              <HugeiconsIcon icon={item.icone} size={18} strokeWidth={2} />
              {item.rotulo}
            </button>
          ),
        )}
      </div>
    </details>
  );
}

function EnviarModelo({
  conversa,
  aoFechar,
  agir,
}: {
  conversa: Detalhe;
  aoFechar: () => void;
  agir: Agir;
}) {
  const [modelo, setModelo] = useState(conversa.modelos[0] ?? "");
  return (
    <Dialogo
      titulo="Enviar modelo"
      aoFechar={aoFechar}
      rodape={
        <>
          <button type="button" onClick={aoFechar}>
            Cancelar
          </button>
          <button
            type="button"
            className="principal"
            disabled={!modelo}
            onClick={() => {
              void agir(() => api.enviar(conversa.id, { modelo }));
              aoFechar();
            }}
          >
            Enviar para {conversa.telefone}
          </button>
        </>
      }
    >
      <label>
        Modelo
        <select value={modelo} onChange={(e) => setModelo(e.target.value)}>
          {conversa.modelos.map((m) => (
            <option key={m} value={m}>
              {rotulo(MODELOS, m)}
            </option>
          ))}
        </select>
      </label>
      {/* O texto do modelo fica cadastrado na Meta: o painel não tem como mostrá-lo. */}
      <p className="nota">O cliente recebe o texto aprovado na Meta, que o painel não mostra.</p>
    </Dialogo>
  );
}

// Só vai à API o que foi preenchido; o resto fica como está. Os valores atuais
// aparecem mascarados: para ver o valor inteiro, "Revelar" na ficha (auditado).
function EditarFicha({
  conversaId,
  aoFechar,
  agir,
}: {
  conversaId: string;
  aoFechar: () => void;
  agir: Agir;
}) {
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [edicao, setEdicao] = useState<Record<string, string>>({});
  const [trocarConta, setTrocarConta] = useState(false);
  const [conta, setConta] = useState<ContaNova>(CONTA_VAZIA);
  const [bancos, setBancos] = useState<Banco[]>([]);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    api
      .ficha(conversaId)
      .then(setFicha)
      .catch((e: Error) => setErro(e.message));
  }, [conversaId]);

  const campo = (nome: string) => ({
    value: edicao[nome] ?? "",
    onChange: (e: { target: { value: string } }) => setEdicao({ ...edicao, [nome]: e.target.value }),
  });

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    const mudanca: EdicaoFicha = Object.fromEntries(
      Object.entries(edicao)
        .map(([k, v]) => [k, v.trim()])
        .filter(([, v]) => v),
    );
    if (mudanca.celular) mudanca.celular = mudanca.celular.replace(/\D/g, "");
    if (trocarConta) {
      const banco = bancos.find((b) => b.codigo === conta.banco_codigo);
      mudanca.conta = { ...conta, banco_nome: banco?.nome ?? "" };
    }
    if (Object.keys(mudanca).length === 0) {
      setErro("Preencha ao menos um campo.");
      return;
    }
    setErro("");
    setSalvando(true);
    try {
      await api.editarFicha(conversaId, mudanca);
      await agir(async () => undefined);
      aoFechar();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Dialogo titulo="Editar ficha" aoFechar={aoFechar}>
      <form className="form-ficha" onSubmit={salvar} id="form-ficha">
        <p className="nota">
          Preencha só o que muda; o resto fica como está. A IA passa a usar os dados novos.
        </p>
        <fieldset>
          <legend>Cliente</legend>
          <label>
            Nome completo
            <input {...campo("nome")} placeholder={ficha?.nome ?? ""} autoComplete="off" />
          </label>
          <label>
            Nascimento
            <input type="date" {...campo("nascimento")} />
            {ficha?.dados.data_nascimento && <small>Hoje: {ficha.dados.data_nascimento}</small>}
          </label>
          <label>
            Sexo
            <select {...campo("sexo")}>
              <option value="">Não mudar</option>
              <option value="F">Feminino</option>
              <option value="M">Masculino</option>
            </select>
          </label>
          <label>
            CPF
            <input
              {...campo("cpf")}
              inputMode="numeric"
              placeholder={ficha?.dados.cpf ?? ""}
              autoComplete="off"
            />
          </label>
          <label>
            E-mail
            <input type="email" {...campo("email")} placeholder={ficha?.dados.email ?? ""} />
          </label>
          <label>
            Celular
            <input
              {...campo("celular")}
              inputMode="tel"
              placeholder="DDD + número, 11 dígitos"
              autoComplete="off"
            />
          </label>
        </fieldset>
        <fieldset>
          <legend>Conta para o Pix</legend>
          <label className="opcao">
            <input
              type="checkbox"
              checked={trocarConta}
              onChange={(e) => setTrocarConta(e.target.checked)}
            />
            Trocar a conta (precisa ser do próprio cliente)
          </label>
          {trocarConta && (
            <CamposConta conta={conta} mudar={setConta} aoCarregarBancos={setBancos} />
          )}
        </fieldset>
        {erro && (
          <p className="erro" role="alert">
            {erro}
          </p>
        )}
        <footer className="form-ficha__acoes">
          <button type="button" onClick={aoFechar}>
            Cancelar
          </button>
          <button type="submit" disabled={salvando}>
            {salvando ? "Salvando…" : "Salvar"}
          </button>
        </footer>
      </form>
    </Dialogo>
  );
}
