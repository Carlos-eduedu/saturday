"""Cliente HTTP mínimo para o OpenRouter.

O ``timeout`` do httpx é aplicado por operação (conexão/leitura), não ao tempo
total. Provedores que mantêm a resposta aberta com chunks lentos podem passar
dos 30 s. Aqui o corpo é lido em streaming e o prazo total é verificado.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


class OpenRouterError(RuntimeError):
    """Falha ao chamar o OpenRouter."""


def post_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    inicio = time.monotonic()
    partes: list[bytes] = []
    try:
        with httpx.stream(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(timeout_s),
        ) as response:
            response.raise_for_status()
            for parte in response.iter_bytes():
                partes.append(parte)
                if time.monotonic() - inicio > timeout_s:
                    raise httpx.TimeoutException("timeout total do OpenRouter")
    except Exception as exc:
        raise OpenRouterError("Falha na chamada ao OpenRouter") from exc

    try:
        return json.loads(b"".join(partes))  # type: ignore[no-any-return]  # json.loads devolve Any
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OpenRouterError("OpenRouter devolveu uma resposta inválida") from exc
