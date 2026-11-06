"""Cliente HTTP do OpenRouter.

O ``timeout`` do httpx é aplicado por operação (conexão/leitura), não ao tempo
total. Provedores que mantêm a resposta aberta com chunks lentos podem passar
do limite. Aqui o corpo é lido em streaming e o prazo total é verificado.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

import httpx


class OpenRouterError(RuntimeError):
    """Falha ao chamar o OpenRouter.

    ``retryable`` indica se a falha é transitória (timeout, conexão, 429 ou 5xx).
    """

    def __init__(
        self,
        mensagem: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(mensagem)
        self.status_code = status_code
        self.retryable = retryable


class OpenRouterClient:
    """Cliente compartilhado para as chamadas do OpenRouter."""

    def __init__(self, http: httpx.Client, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        inicio = time.monotonic()
        partes: list[bytes] = []
        try:
            with self._http.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise OpenRouterError(
                "Falha na chamada ao OpenRouter",
                status_code=status,
                retryable=status == 429 or status >= 500,
            ) from exc
        except httpx.TransportError as exc:
            raise OpenRouterError(
                "Falha na chamada ao OpenRouter",
                retryable=True,
            ) from exc
        except OpenRouterError:
            raise
        except Exception as exc:
            raise OpenRouterError("Falha na chamada ao OpenRouter") from exc

        try:
            return cast(dict[str, Any], json.loads(b"".join(partes)))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OpenRouterError("OpenRouter devolveu uma resposta inválida") from exc
