"""Unit tests for TriviaGenerator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.llm.trivia_generator import TriviaGenerator


class TestTriviaGenerator:
    @pytest.mark.asyncio
    async def test_generate_with_song(self, mock_ollama_client: AsyncMock) -> None:
        gen = TriviaGenerator(client=mock_ollama_client)
        result = await gen.generate(artist_name="Queen", song_name="Bohemian Rhapsody")

        assert result is not None
        assert "Freddie Mercury" in result
        mock_ollama_client.generate.assert_awaited_once()

        # Check the prompt was constructed properly.
        prompt_arg = mock_ollama_client.generate.call_args[0][0]
        assert "Queen" in prompt_arg
        assert "Bohemian Rhapsody" in prompt_arg

    @pytest.mark.asyncio
    async def test_generate_without_song(self, mock_ollama_client: AsyncMock) -> None:
        gen = TriviaGenerator(client=mock_ollama_client)
        result = await gen.generate(artist_name="Radiohead")

        assert result is not None
        prompt_arg = mock_ollama_client.generate.call_args[0][0]
        assert "Radiohead" in prompt_arg

    @pytest.mark.asyncio
    async def test_generate_handles_empty_response(self, mock_ollama_client: AsyncMock) -> None:
        mock_ollama_client.generate.return_value = ""
        gen = TriviaGenerator(client=mock_ollama_client)
        result = await gen.generate(artist_name="Pink Floyd")

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_handles_exception(self, mock_ollama_client: AsyncMock) -> None:
        mock_ollama_client.generate.side_effect = RuntimeError("boom")
        gen = TriviaGenerator(client=mock_ollama_client)
        result = await gen.generate(artist_name="The Beatles")

        assert result is None
