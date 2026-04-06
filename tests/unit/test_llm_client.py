"""Unit tests for OllamaClient."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.config.schemas import LLMConfig
from src.llm.client import OllamaClient
from src.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
)
from tests.fixtures.mock_ollama_responses import GENERATE_SUCCESS, TAGS_RESPONSE

_FAKE_REQUEST = httpx.Request("POST", "http://localhost:11434/api/generate")


@pytest.fixture()
def llm_client(llm_config: LLMConfig) -> OllamaClient:
    return OllamaClient(config=llm_config)


class TestOllamaClient:
    @pytest.mark.asyncio
    async def test_generate_success(self, llm_client: OllamaClient) -> None:
        mock_response = httpx.Response(200, json=GENERATE_SUCCESS, request=_FAKE_REQUEST)

        with patch.object(llm_client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await llm_client.generate("Tell me about Queen")

        assert "Freddie Mercury" in result
        mock_post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_connection_error(self, llm_client: OllamaClient) -> None:
        with patch.object(llm_client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")
            with pytest.raises(LLMConnectionError, match="Cannot reach Ollama"):
                await llm_client.generate("hello")

    @pytest.mark.asyncio
    async def test_generate_timeout(self, llm_client: OllamaClient) -> None:
        with patch.object(llm_client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ReadTimeout("timed out")
            with pytest.raises(LLMTimeoutError, match="timed out"):
                await llm_client.generate("hello")

    @pytest.mark.asyncio
    async def test_generate_bad_response_shape(self, llm_client: OllamaClient) -> None:
        bad_response = httpx.Response(200, json={"unexpected": "data"}, request=_FAKE_REQUEST)
        with patch.object(llm_client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = bad_response
            with pytest.raises(LLMResponseError, match="Unexpected"):
                await llm_client.generate("hello")

    @pytest.mark.asyncio
    async def test_generate_http_error(self, llm_client: OllamaClient) -> None:
        err_response = httpx.Response(500, json={"error": "model not found"}, request=_FAKE_REQUEST)
        with patch.object(llm_client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = err_response
            with pytest.raises(LLMResponseError, match="HTTP 500"):
                await llm_client.generate("hello")

    @pytest.mark.asyncio
    async def test_is_available_true(self, llm_client: OllamaClient) -> None:
        mock_resp = httpx.Response(200, json=TAGS_RESPONSE)
        with patch.object(llm_client._http, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            assert await llm_client.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self, llm_client: OllamaClient) -> None:
        with patch.object(llm_client._http, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("refused")
            assert await llm_client.is_available() is False

    @pytest.mark.asyncio
    async def test_aclose(self, llm_client: OllamaClient) -> None:
        with patch.object(llm_client._http, "aclose", new_callable=AsyncMock) as mock_close:
            await llm_client.aclose()
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, llm_config: LLMConfig) -> None:
        async with OllamaClient(config=llm_config) as client:
            assert client is not None
