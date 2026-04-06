"""DJ trivia script generator — prompt engineering over OllamaClient."""

from __future__ import annotations

from src.llm.client import OllamaClient
from src.utils.logger import get_logger

_logger = get_logger("llm.trivia_generator")

_SYSTEM_PERSONA = (
    "You are a laid-back, enthusiastic music nerd DJ on a radio show. "
    "You love sharing obscure historical trivia, band anecdotes, and studio secrets. "
    "Your tone is always casual, friendly, and podcast-like — as if chatting with a friend. "
    "Keep responses concise: 1–2 sentences maximum."
)

_TRIVIA_TEMPLATE = (
    "{persona}\n\n"
    "Give me one single fun trivia fact about {artist}"
    "{song_fragment}. "
    "Respond with ONLY the trivia fact — no preamble, no labels, no quotes."
)


class TriviaGenerator:
    """
    Generates a short, DJ-persona trivia script about the upcoming artist.

    Args:
        client: Configured :class:`OllamaClient` instance.
    """

    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    async def generate(
        self,
        artist_name: str,
        song_name: str | None = None,
    ) -> str | None:
        """
        Generate a 1–2 sentence trivia fact about *artist_name*.

        Args:
            artist_name: Name of the artist being played.
            song_name:   Optional song title for more specific trivia.

        Returns:
            A single trivia string, or *None* if generation fails.
        """
        song_fragment = f" and the song '{song_name}'" if song_name else ""
        prompt = _TRIVIA_TEMPLATE.format(
            persona=_SYSTEM_PERSONA,
            artist=artist_name,
            song_fragment=song_fragment,
        )

        _logger.info(
            "Generating trivia for artist='%s', song='%s'.",
            artist_name,
            song_name or "N/A",
        )

        try:
            result = await self._client.generate(prompt)
            if not result:
                _logger.warning("Ollama returned an empty response.")
                return None
            _logger.debug("Trivia generated: %s", result)
            return result
        except Exception as exc:
            _logger.error("Trivia generation failed: %s", exc)
            return None
