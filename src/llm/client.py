"""Async HTTP client for the Ollama /api/generate endpoint."""

from __future__ import annotations

import httpx

from src.config.schemas import LLMConfig
from src.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
)
from src.utils.logger import get_logger

_logger = get_logger("llm.client")


class OllamaClient:
    """
    Thin async wrapper around the Ollama REST API.

    Uses a persistent :class:`httpx.AsyncClient` for connection reuse
    across multiple inference calls during a session.

    Args:
        config: LLM configuration (endpoint, model, temperature, timeout).
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.endpoint,
            timeout=httpx.Timeout(config.timeout_sec),
        )

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Send *prompt* to Ollama and return the generated text.

        Args:
            prompt:      Input prompt string.
            temperature: Override config temperature for this call.
            max_tokens:  Optional Ollama ``num_predict`` output token limit.

        Returns:
            Generated text response (stripped of leading/trailing whitespace).

        Raises:
            LLMConnectionError: Ollama server is unreachable.
            LLMTimeoutError:    Inference exceeded the configured timeout.
            LLMResponseError:   Ollama returned an unexpected response shape.
        """
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self._config.temperature,
                "num_ctx": 2048,
            },
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        _logger.debug("Sending inference request (model=%s).", self._config.model)

        try:
            response = await self._http.post("/api/generate", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Cannot reach Ollama at '{self._config.endpoint}'. "
                "Is 'ollama serve' running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama inference timed out after {self._config.timeout_sec}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMResponseError(
                f"Ollama returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc

        try:
            data = response.json()
            return data["response"].strip()
        except (KeyError, ValueError) as exc:
            raise LLMResponseError(
                f"Unexpected Ollama response shape: {response.text[:200]}"
            ) from exc

    async def is_available(self) -> bool:
        """
        Probe the Ollama server with a lightweight health check.

        Returns:
            *True* if the server responds, *False* otherwise.
        """
        try:
            resp = await self._http.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._http.aclose()

    # ------------------------------------------------------------------ #
    # Context-manager support                                             #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
