// Anexo de uma mensagem e o visor que ele abre. A animação é a do Morphing
// Dialog (motion-primitives): a miniatura cresce até virar o conteúdo aberto e
// encolhe de volta. Aqui ela sai do <dialog> nativo com a View Transitions API,
// sem o `motion`; navegador sem a API abre o visor direto.
import { type MouseEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  Cancel01Icon,
  Download04Icon,
  File01Icon,
  Loading03Icon,
  Pdf01Icon,
  Video01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { rotuloDoAnexo, type TipoDeAnexo, tipoDoAnexo } from "../anexos";
import { RefineFrame, type StatusQuadro } from "./RefineFrame";
import "./VisorDeMidia.css";

const NOME_PADRAO: Record<TipoDeAnexo, string> = {
  imagem: "Imagem enviada",
  audio: "Áudio",
  video: "Vídeo",
  pdf: "Documento PDF",
  outro: "Arquivo",
};
const ICONE = { pdf: Pdf01Icon, video: Video01Icon, outro: File01Icon };

// `blob`: o arquivo já em memória (imagem e PDF); `falhou`: não deu para buscar.
type Aberto = { blob: string | null; falhou: boolean };

// Troca o estado com a miniatura "virando" o visor. O nome da transição
// (`midia`) fica no gatilho antes da troca e no conteúdo do visor depois.
function comTransicao(mudar: () => void): Promise<void> {
  if (!document.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    mudar();
    return Promise.resolve();
  }
  return document.startViewTransition(() => flushSync(mudar)).finished.catch(() => undefined);
}

export function AnexoDaMensagem({ url, mime, nome: nomeDado }: { url: string; mime: string; nome?: string | null }) {
  const tipo = tipoDoAnexo(mime);
  const nome = nomeDado ?? NOME_PADRAO[tipo];
  const gatilho = useRef<HTMLAnchorElement>(null);
  const [aberto, setAberto] = useState<Aberto | null>(null);
  const [abrindo, setAbrindo] = useState(false);
  const [quadro, setQuadro] = useState<StatusQuadro>("carregando");

  // O arquivo em memória vive só enquanto o visor está aberto.
  useEffect(
    () => () => {
      if (aberto?.blob) URL.revokeObjectURL(aberto.blob);
    },
    [aberto],
  );

  async function abrir(e: MouseEvent) {
    // Ctrl/⌘/Shift-clique segue o link: outra aba.
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    if (abrindo || aberto) return;
    const proximo: Aberto = { blob: null, falhou: false };
    if (tipo !== "video") {
      // Busca antes de abrir: a resposta é `no-store`, e um <img> novo no visor
      // começaria vazio no meio da animação. O PDF em memória também dispensa
      // afrouxar o `X-Frame-Options: DENY` do nginx.
      setAbrindo(true);
      try {
        const resposta = await fetch(url);
        if (!resposta.ok) throw new Error(String(resposta.status));
        proximo.blob = URL.createObjectURL(await resposta.blob());
      } catch {
        proximo.falhou = true;
      }
      setAbrindo(false);
    }
    const el = gatilho.current;
    if (el) el.style.viewTransitionName = "midia";
    await comTransicao(() => {
      if (el) el.style.viewTransitionName = "";
      setAberto(proximo);
    });
  }

  function fechar() {
    const el = gatilho.current;
    void comTransicao(() => {
      setAberto(null);
      if (el) el.style.viewTransitionName = "midia";
    }).then(() => {
      if (!el) return;
      el.style.viewTransitionName = "";
      el.focus({ preventScroll: true });
    });
  }

  const visor = aberto && <Visor url={url} nome={nome} tipo={tipo} aberto={aberto} aoFechar={fechar} />;

  if (tipo === "imagem") {
    // Na falha não há link (botão dentro de link não vale); "Tentar de novo"
    // monta um <img> novo, que refaz o pedido.
    if (quadro === "falhou")
      return (
        <div className="anexo-imagem">
          <RefineFrame status={quadro} aoTentarDeNovo={() => setQuadro("carregando")} />
        </div>
      );
    return (
      <>
        <a ref={gatilho} className="anexo-imagem" href={url} onClick={abrir} aria-busy={abrindo || undefined}>
          <RefineFrame status={quadro}>
            <img
              src={url}
              alt={nome}
              loading="lazy"
              onLoad={() => setQuadro("pronto")}
              onError={() => setQuadro("falhou")}
            />
          </RefineFrame>
        </a>
        {visor}
      </>
    );
  }

  const rotulo = rotuloDoAnexo(tipo, nomeDado);
  // Sem prévia segura, o cartão só baixa: abrir o arquivo no painel rodaria o
  // que o cliente mandou.
  if (tipo === "outro" || tipo === "audio")
    return (
      <a className="anexo-cartao" href={url} download={nome}>
        <HugeiconsIcon icon={File01Icon} size={22} strokeWidth={1.8} />
        <span className="dados-anexo">
          <span className="nome">{nome}</span>
          <small>{rotulo} · baixar</small>
        </span>
        <HugeiconsIcon icon={Download04Icon} size={18} strokeWidth={2} />
      </a>
    );
  return (
    <>
      <a ref={gatilho} className="anexo-cartao" href={url} onClick={abrir} aria-busy={abrindo || undefined}>
        <HugeiconsIcon icon={ICONE[tipo]} size={22} strokeWidth={1.8} />
        <span className="dados-anexo">
          <span className="nome">{nome}</span>
          <small>{rotulo}</small>
        </span>
        {abrindo && (
          <span className="anexo-cartao__girando">
            <HugeiconsIcon icon={Loading03Icon} size={18} strokeWidth={2} />
          </span>
        )}
      </a>
      {visor}
    </>
  );
}

function Visor({
  url,
  nome,
  tipo,
  aberto,
  aoFechar,
}: {
  url: string;
  nome: string;
  tipo: TipoDeAnexo;
  aberto: Aberto;
  aoFechar: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // Layout effect: o visor já está aberto quando a transição fotografa a tela.
  useLayoutEffect(() => {
    ref.current?.showModal();
  }, []);
  // O Chrome do Android, por exemplo, não desenha PDF embutido.
  const semLeitor = tipo === "pdf" && !navigator.pdfViewerEnabled;

  return (
    <dialog
      ref={ref}
      className="visor"
      aria-label={nome}
      // Esc: fecha pelo nosso caminho, para a mídia encolher de volta.
      onCancel={(e) => {
        e.preventDefault();
        aoFechar();
      }}
      onClose={aoFechar}
      // Clique fora do conteúdo e dos controles fecha.
      onClick={(e) => (e.target as Element).closest(".visor__conteudo, a, button") || aoFechar()}
    >
      <div className="visor__barra">
        <span className="visor__nome">{nome}</span>
        <a href={url} target="_blank" rel="noreferrer">
          Abrir em outra aba
        </a>
        <a href={url} download={nome}>
          <HugeiconsIcon icon={Download04Icon} size={18} strokeWidth={2} />
          Baixar
        </a>
        <button type="button" className="visor__fechar" onClick={aoFechar} aria-label="Fechar" autoFocus>
          <HugeiconsIcon icon={Cancel01Icon} size={20} strokeWidth={2} />
        </button>
      </div>
      <div className="visor__conteudo">
        {aberto.falhou ? (
          <p className="visor__aviso">Não deu para abrir este arquivo. Ele pode já ter sido apagado.</p>
        ) : semLeitor ? (
          <p className="visor__aviso">Este aparelho não mostra PDF aqui. Use "Abrir em outra aba".</p>
        ) : tipo === "imagem" ? (
          <img src={aberto.blob ?? url} alt={nome} />
        ) : tipo === "pdf" ? (
          <iframe src={aberto.blob ?? url} title={nome} />
        ) : (
          <video src={url} controls />
        )}
      </div>
    </dialog>
  );
}
