"""
Manual test: verify Ollama is running and can generate trivia.

Requirements:
  - Ollama installed and running (``ollama serve``)
  - A model pulled (``ollama pull mistral``)

Run:
  python -m pytest manual_tests/test_ollama_connection.py -v -s
"""

from __future__ import annotations

import pytest

from src.config.schemas import LLMConfig
from src.llm.client import OllamaClient
from src.llm.trivia_generator import TriviaGenerator


@pytest.mark.manual
class TestRealOllama:
    @pytest.mark.asyncio
    async def test_ollama_is_reachable(self) -> None:
        config = LLMConfig()
        async with OllamaClient(config=config) as client:
            available = await client.is_available()
            assert available, (
                f"Ollama not reachable at {config.endpoint}. "
                "Run 'ollama serve' first."
            )
            print(f"Ollama is running at {config.endpoint}")

    @pytest.mark.asyncio
    async def test_generate_basic_response(self) -> None:
        config = LLMConfig(timeout_sec=120)
        async with OllamaClient(config=config) as client:
            response = await client.generate("Say hello in one word.")
            assert response, "Empty response from Ollama."
            print(f"Ollama response: {response}")

    @pytest.mark.asyncio
    async def test_trivia_generation(self) -> None:
        config = LLMConfig(timeout_sec=120)
        async with OllamaClient(config=config) as client:
            gen = TriviaGenerator(client=client)
            trivia = await gen.generate(
                artist_name="Queen",
                song_name="Bohemian Rhapsody",
            )
            assert trivia, "No trivia generated."
            print(f"DJ says: {trivia}")
