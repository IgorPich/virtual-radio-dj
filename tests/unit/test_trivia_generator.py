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
        assert "passionate, talkative late-night radio host" in prompt_arg
        assert "Every segment MUST include" in prompt_arg
        assert "artist/song/production backstory" in prompt_arg
        assert "fictional anecdote" in prompt_arg
        assert "strong personal opinion" in prompt_arg
        assert "3–5 flowing sentences" in prompt_arg
        assert mock_ollama_client.generate.call_args.kwargs["max_tokens"] == 320

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

    @pytest.mark.asyncio
    async def test_generate_fake_commercial_prompt(
        self, mock_ollama_client: AsyncMock
    ) -> None:
        mock_ollama_client.generate.return_value = "Buy Mood Paste, the snack that judges you back."
        gen = TriviaGenerator(client=mock_ollama_client)

        result = await gen.generate_fake_commercial(hour=9)

        assert result is not None
        prompt_arg = mock_ollama_client.generate.call_args[0][0]
        assert "fictional comedy radio commercial" in prompt_arg
        assert "absurd, satirical" in prompt_arg
        assert "do NOT mention any real game" in prompt_arg
        assert "real brands" in prompt_arg
        assert "real products" in prompt_arg
        assert "20 to 35 seconds" in prompt_arg
