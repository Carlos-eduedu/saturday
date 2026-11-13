"""Áudio gravado no painel → mensagem de voz da Meta (ogg com opus, mono).

O navegador grava em webm (Chrome), ogg (Firefox) ou mp4 (Safari); a Meta só
trata como voz o `audio/ogg` com opus. O ffmpeg roda por pipe, sem tocar o
disco, e vem na imagem (`apps/core/Dockerfile`).
"""

from __future__ import annotations

import shutil
import subprocess

TIMEOUT_S = 60


class ErroConversao(Exception):
    """O áudio não converteu: arquivo corrompido ou ffmpeg ausente."""


def para_ogg_opus(dados: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ErroConversao("ffmpeg não instalado")
    try:
        feito = subprocess.run(  # noqa: S603 - argumentos fixos, entrada só por stdin
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-vn",
                "-ac",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-f",
                "ogg",
                "pipe:1",
            ],
            input=dados,
            capture_output=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ErroConversao(type(exc).__name__) from exc
    if feito.returncode != 0 or not feito.stdout:
        motivo = feito.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["vazio"]
        raise ErroConversao(f"ffmpeg {feito.returncode}: {motivo[0][:200]}")
    return feito.stdout
