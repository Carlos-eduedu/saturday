import { useEffect, useRef, useState } from "react";

// Gravação de áudio no navegador. O formato é o primeiro que o navegador grava
// entre os que a API aceita; na Meta o worker converte para voz (ogg/opus) e a
// Evolution converte sozinha.
const FORMATOS = ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/mp4"];
export const LIMITE_GRAVACAO_S = 5 * 60;

export type Gravador = {
  gravando: boolean;
  segundos: number;
  erro: string;
  suportado: boolean;
  iniciar: () => Promise<void>;
  parar: () => void;
  cancelar: () => void;
};

export function useGravador(aoTerminar: (audio: File) => void): Gravador {
  const [gravando, setGravando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [erro, setErro] = useState("");
  const gravador = useRef<MediaRecorder | null>(null);
  const descartar = useRef(false);
  const terminar = useRef(aoTerminar);
  terminar.current = aoTerminar;

  const suportado =
    typeof MediaRecorder !== "undefined" && typeof navigator !== "undefined" && !!navigator.mediaDevices;

  useEffect(() => {
    if (!gravando) return undefined;
    const inicio = Date.now();
    const id = setInterval(() => {
      const s = Math.floor((Date.now() - inicio) / 1000);
      setSegundos(s);
      if (s >= LIMITE_GRAVACAO_S) gravador.current?.stop();
    }, 250);
    return () => clearInterval(id);
  }, [gravando]);

  // Saiu da tela gravando: solta o microfone sem gerar arquivo.
  useEffect(
    () => () => {
      descartar.current = true;
      gravador.current?.stop();
    },
    [],
  );

  async function iniciar() {
    setErro("");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setErro("Sem acesso ao microfone. Libere a permissão do navegador e tente de novo.");
      return;
    }
    const formato = FORMATOS.find((f) => MediaRecorder.isTypeSupported(f)) ?? "";
    const rec = new MediaRecorder(stream, formato ? { mimeType: formato } : undefined);
    const partes: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size > 0 && partes.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      setGravando(false);
      gravador.current = null;
      if (descartar.current || partes.length === 0) return;
      const tipo = (rec.mimeType || formato || "audio/webm").split(";")[0];
      const extensao = tipo === "audio/mp4" ? "m4a" : tipo.split("/")[1];
      terminar.current(new File(partes, `audio.${extensao}`, { type: tipo }));
    };
    descartar.current = false;
    gravador.current = rec;
    setSegundos(0);
    rec.start();
    setGravando(true);
  }

  return {
    gravando,
    segundos,
    erro,
    suportado,
    iniciar,
    parar: () => gravador.current?.stop(),
    cancelar: () => {
      descartar.current = true;
      gravador.current?.stop();
    },
  };
}
