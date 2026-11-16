// O que o painel pode desenhar de um anexo. O arquivo vem do cliente, com o
// tipo que ele declarou: só entra aqui o que o navegador mostra sem rodar nada
// do arquivo. HTML, SVG e o resto são "outro": só para baixar, nunca abrir.
export type TipoDeAnexo = "imagem" | "audio" | "video" | "pdf" | "outro";

const IMAGENS = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);

export function tipoDoAnexo(mime: string): TipoDeAnexo {
  const limpo = (mime.split(";")[0] ?? "").trim().toLowerCase();
  if (IMAGENS.has(limpo)) return "imagem";
  if (limpo === "application/pdf") return "pdf";
  if (limpo.startsWith("audio/")) return "audio";
  if (limpo.startsWith("video/")) return "video";
  return "outro";
}

// Rótulo curto do cartão: "PDF", "Vídeo" ou a extensão do nome ("DOCX").
export function rotuloDoAnexo(tipo: TipoDeAnexo, nome: string | null | undefined): string {
  if (tipo === "pdf") return "PDF";
  if (tipo === "video") return "Vídeo";
  const extensao = /\.([a-z0-9]{1,5})$/i.exec(nome ?? "")?.[1];
  return extensao ? extensao.toUpperCase() : "Arquivo";
}
