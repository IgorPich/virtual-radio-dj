"""DJ monologue script generator — prompt engineering over OllamaClient."""

from __future__ import annotations

from datetime import datetime

from src.llm.client import OllamaClient
from src.spotify.models import Track
from src.utils.logger import get_logger

_logger = get_logger("llm.trivia_generator")


def is_duo_time() -> bool:
    """Return *True* during the morning duo show window (08:00–10:59)."""
    return 8 <= datetime.now().hour < 11


_SYSTEM_PERSONA = (
    "You are a passionate, talkative late-night radio host — warm, vivid, curious, "
    "and genuinely obsessed with music. You're not reading liner notes; you're in "
    "the studio with the lights low, talking to listeners like they're riding shotgun "
    "through the night with you. Use natural speech — contractions, casual phrasing, "
    "and real in-character opinions. Never use 'Fun fact:', 'Did you know:', or "
    "'trivia'. Just talk.\n"
    "Every segment MUST include at least one of these: a real, verified bit of "
    "artist/song/production backstory from the supplied context; a short, clearly "
    "fictional anecdote inspired by the song's vibe; or a strong personal opinion "
    "about why the track works.\n"
    "Write 3–5 flowing sentences with enough personality to feel like a real "
    "late-night break. No one-liners.\n"
    "CRITICAL RULE: Only say things you know for certain are true. "
    "If you are not sure about specific facts, do NOT invent facts — instead make "
    "it clear you're riffing fictionally from the mood, or give an honest personal "
    "take on the sound. Honesty over invented history, always."
)

# ── Duo mode personas ─────────────────────────────────────────────────────────

_SYSTEM_DUO_PERSONA = (
    "You are writing a live on-air script for TWO radio presenters: Ryan (the main host) "
    "and {cohost_name} (co-host). They are co-presenting the morning show together — warm, playful, "
    "and genuinely into the music. Their banter is natural and light, never forced.\n"
    "Format EVERY line as either '[RYAN]: ...' or '[{cohost_label}]: ...' with no other text.\n"
    "Keep the total to 4–6 lines (alternating voices). No more.\n"
    "CRITICAL RULE: Only say things you know for certain are true about the artist or song. "
    "If unsure of specific facts, talk about the feel, the mood, the energy, or just "
    "hype the listener up honestly. Never invent tours, albums, or history."
)


def _artist_context_block(artist_info: dict | None) -> str:
    """Build a factual context block from Spotify artist data to ground the LLM."""
    if not artist_info:
        return ""
    genres = artist_info.get("genres") or []
    popularity = artist_info.get("popularity") or 0
    followers = artist_info.get("followers") or 0
    if not genres and not popularity:
        return ""
    parts: list[str] = []
    if genres:
        parts.append(f"Genres: {', '.join(genres[:5])}")
    if popularity:
        parts.append(f"Spotify popularity score: {popularity}/100")
    if followers:
        parts.append(f"Followers: {followers:,}")
    return (
        "Verified Spotify data about this artist:\n"
        + "\n".join(f"  - {p}" for p in parts)
        + "\nBase your commentary strictly on this data. Do not invent tours, albums, or history not listed here.\n"
    )

# ── Main prompt (current track ending, next track known) ─────────────────────

_PROMPT_FULL = (
    "{persona}\n\n"
    "{artist_context}"
    "You just finished playing '{current_song}' by {current_artist}, "
    "and '{next_song}' by {next_artist} is coming up right after.\n"
    "{prev_line}\n"
    "Write your live on-air monologue now — speak it, don't describe it.\n"
    "Structure it naturally like this:\n"
    "— Two to three sentences reacting to '{current_song}': how it landed, what made it hit, "
    "the mood or energy it had, plus one backstory detail, fictional vibe anecdote, "
    "or strong personal opinion.\n"
    "— One to two sentences building anticipation for '{next_song}' by {next_artist}: "
    "what vibe to expect, why it belongs here, get the listener excited.\n"
    "Sound like you're actually there in the studio, loving every second of it.\n"
    "Aim for 3–5 flowing sentences total.\n"
    "Respond with ONLY the spoken words — no stage directions, no labels, no quotes."
)

# ── Fallback prompt (no next track known) ────────────────────────────────────

_PROMPT_NO_NEXT = (
    "{persona}\n\n"
    "{artist_context}"
    "You just finished playing '{current_song}' by {current_artist}.\n"
    "{prev_line}\n"
    "Write your live on-air monologue — just speak it naturally.\n"
    "React to the song: what was the feeling, the energy, what made it stand out. "
    "Include one real backstory detail if the context supports it, or a clearly "
    "fictional little anecdote inspired by the vibe, or a strong personal take. "
    "Then keep the momentum going and keep the listener locked in.\n"
    "3–5 flowing sentences, human and present, like you're live on air right now.\n"
    "Respond with ONLY the spoken words — no stage directions, no labels, no quotes."
)

# ── Duo prompt (with next track) ─────────────────────────────────────────────

_PROMPT_FULL_DUO = (
    "{persona}\n\n"
    "{artist_context}"
    "You just finished playing '{current_song}' by {current_artist}, "
    "and '{next_song}' by {next_artist} is coming up right after.\n"
    "{prev_line}\n"
    "Write the live on-air script for Ryan and {cohost_name} now.\n"
    "Structure the dialogue naturally:\n"
    "— Ryan opens with a reaction to '{current_song}'.\n"
    "— {cohost_name} adds their take — agrees, disagrees, or builds on it.\n"
    "— Ryan or {cohost_name} teases '{next_song}' by {next_artist} and gets the listener excited.\n"
    "Format every line as '[RYAN]: ...' or '[{cohost_label}]: ...' — nothing else."
)

# ── Duo fallback prompt (no next track) ──────────────────────────────────────

_PROMPT_NO_NEXT_DUO = (
    "{persona}\n\n"
    "{artist_context}"
    "You just finished playing '{current_song}' by {current_artist}.\n"
    "{prev_line}\n"
    "Write the live on-air script for Ryan and {cohost_name} now.\n"
    "React to the song together — what was the feeling, the energy, what made it stand out. "
    "Keep the energy up and tease what's coming next.\n"
    "Format every line as '[RYAN]: ...' or '[{cohost_label}]: ...' — nothing else."
)

# ── News bulletin prompts ─────────────────────────────────────────────────────

_NEWS_SYSTEM_PERSONA = (
    "You are a professional radio news reader for Midnight Radio. "
    "Your delivery is warm, clear, and authoritative — like a real broadcast journalist. "
    "Present the news naturally and concisely. "
    "CRITICAL: Do NOT add, invent, or embellish any facts beyond the exact headlines "
    "provided to you. Keep each news section to 1–2 natural spoken sentences. "
    "End with a brief handback phrase like 'And that's the news — back to the music.'"
)

_NEWS_PROMPT = (
    "{system}\n\n"
    "Write a live top-of-hour radio news bulletin. "
    "It is {greeting}, {time_label} o'clock.\n\n"
    "Use ONLY the following real headlines — do not invent or expand stories:\n\n"
    "WORLD NEWS:\n{world}\n\n"
    "POLAND:\n{country}\n\n"
    "WARSAW:\n{local}\n\n"
    "{weather_section}"
    "Structure: Open with a brief time greeting. Cover world, Poland, and Warsaw sections "
    "in that order. Close with a one-sentence handback to music.\n"
    "Respond with ONLY the spoken bulletin text — no labels, no stage directions."
)

_FAKE_COMMERCIAL_PROMPT = (
    "You are writing a fictional comedy radio commercial for Midnight Radio.\n"
    "Style: absurd, satirical, fast, and highly entertaining, with the chaotic energy "
    "of open-world crime-game radio commercials, but do NOT mention any real game, "
    "real brands, copyrighted characters, real companies, or real products.\n"
    "The ad must be for a completely fictional product, service, or lifestyle scam.\n"
    "Make it obviously comedic and fictional, not a real endorsement.\n"
    "Keep it short: about 20 to 35 seconds spoken, roughly 55 to 85 words.\n"
    "No stage directions, no speaker labels, no legal boilerplate, no quotes. "
    "Respond with ONLY the spoken commercial copy.\n"
    "It is currently {time_label} o'clock."
)

_HOUR_NAMES = [
    "midnight", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
    "noon", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
]


class TriviaGenerator:
    """
    Generates a 3–4 sentence DJ monologue.

    The LLM receives context for the current track (ending), the next track
    (upcoming), and optionally the previous track.  It autonomously decides
    which artist has the more interesting story and builds the monologue around
    that choice while still acknowledging the ending track and announcing the next.

    Args:
        client: Configured :class:`OllamaClient` instance.
    """

    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    async def generate(
        self,
        artist_name: str,
        song_name: str | None = None,
        previous_track: Track | None = None,
        current_track: Track | None = None,
        next_track: Track | None = None,
        artist_info: dict | None = None,
        duo_mode: bool | None = None,
        cohost_name: str = "Emma",
    ) -> str | None:
        """
        Generate a 3–4 sentence DJ monologue.

        The LLM is given all available track context and instructed to focus
        on whichever artist (current or next) has the more interesting story.

        Args:
            artist_name:    Fallback artist name when *current_track* is absent.
            song_name:      Fallback song name when *current_track* is absent.
            previous_track: The track that played before the current one.
            current_track:  The track that is ending right now.
            next_track:     The next track in the queue.
            artist_info:    Optional Spotify artist metadata for grounding.
            duo_mode:       Force duo-mode on (*True*) or off (*False*).
                            *None* (default) auto-detects via :func:`is_duo_time`.

        Returns:
            A monologue string, or *None* if generation fails.
        """
        cur_artist = current_track.artist if current_track else artist_name
        cur_song = current_track.name if current_track else (song_name or artist_name)

        active_duo = is_duo_time() if duo_mode is None else duo_mode
        prompt = self._build_prompt(
            cur_artist, cur_song, previous_track, next_track, artist_info,
            duo_mode=active_duo,
            cohost_name=cohost_name,
        )

        _logger.info(
            "Generating DJ monologue (duo=%s) — prev='%s', current='%s', next='%s'.",
            active_duo,
            f"{previous_track.artist} – {previous_track.name}" if previous_track else "N/A",
            f"{cur_artist} – {cur_song}",
            f"{next_track.artist} – {next_track.name}" if next_track else "N/A",
        )

        try:
            result = await self._client.generate(prompt, max_tokens=320)
            if not result:
                _logger.warning("Ollama returned an empty response.")
                return None
            _logger.debug("DJ monologue generated: %s", result)
            return result
        except Exception as exc:
            _logger.error("Monologue generation failed: %s", exc)
            return None

    async def generate_news_script(self, news: "NewsData", hour: int) -> str:
        """
        Generate a broadcast-ready news bulletin script from live headlines.

        The LLM is grounded strictly on the provided headlines and instructed not
        to add or invent facts.  Falls back to the template formatter if the LLM
        call fails or returns an empty response.

        Args:
            news:  Structured news headlines from the fetcher.
            hour:  Current hour (0–23) used for the opening greeting.

        Returns:
            A broadcast-ready spoken script string.
        """
        from src.news.bulletin_generator import NewsBulletinGenerator
        from src.news.fetcher import NewsData  # noqa: F401 — used for type check only

        if 5 <= hour < 12:
            greeting = "good morning"
        elif 12 <= hour < 18:
            greeting = "good afternoon"
        else:
            greeting = "good evening"

        time_label = _HOUR_NAMES[hour % 24]
        weather_section = (
            f"WEATHER:\n{news.weather}\n\n"
            if news.weather
            else ""
        )

        prompt = _NEWS_PROMPT.format(
            system=_NEWS_SYSTEM_PERSONA,
            greeting=greeting,
            time_label=time_label,
            world=news.world or "No current headlines available.",
            country=news.country or "No current headlines available.",
            local=news.local or "No current headlines available.",
            weather_section=weather_section,
        )

        _logger.info("Generating news bulletin script via LLM (hour=%02d).", hour)
        try:
            result = await self._client.generate(prompt)
            if result:
                _logger.debug("News bulletin script generated (%d chars).", len(result))
                return result
            _logger.warning("LLM returned empty news script; falling back to template.")
        except Exception as exc:
            _logger.error(
                "News bulletin LLM failed: %s — falling back to template.", exc
            )

        return NewsBulletinGenerator().format(news, hour)

    async def generate_fake_commercial(self, hour: int) -> str | None:
        """
        Generate a short fictional satirical radio commercial.

        The output is intentionally fictional and avoids real brands/products
        while preserving the absurd commercial energy requested for the station.
        """
        prompt = _FAKE_COMMERCIAL_PROMPT.format(
            time_label=_HOUR_NAMES[hour % 24],
        )

        _logger.info("Generating fake commercial script via LLM (hour=%02d).", hour)
        try:
            result = await self._client.generate(prompt)
            if not result:
                _logger.warning("LLM returned empty fake commercial script.")
                return None
            return result
        except Exception as exc:
            _logger.error("Fake commercial generation failed: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Prompt construction                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_prompt(
        cur_artist: str,
        cur_song: str,
        previous_track: Track | None,
        next_track: Track | None,
        artist_info: dict | None = None,
        duo_mode: bool = False,
        cohost_name: str = "Emma",
    ) -> str:
        """Select and fill the appropriate prompt template."""
        prev_line = (
            f"- Track that played before that: '{previous_track.name}' "
            f"by {previous_track.artist}"
            if previous_track
            else ""
        )
        artist_context = _artist_context_block(artist_info)
        cohost_label = cohost_name.upper()
        persona = (
            _SYSTEM_DUO_PERSONA.format(
                cohost_name=cohost_name,
                cohost_label=cohost_label,
            )
            if duo_mode
            else _SYSTEM_PERSONA
        )

        if next_track:
            template = _PROMPT_FULL_DUO if duo_mode else _PROMPT_FULL
            return template.format(
                persona=persona,
                artist_context=artist_context,
                current_song=cur_song,
                current_artist=cur_artist,
                next_song=next_track.name,
                next_artist=next_track.artist,
                prev_line=prev_line,
                cohost_name=cohost_name,
                cohost_label=cohost_label,
            )

        template = _PROMPT_NO_NEXT_DUO if duo_mode else _PROMPT_NO_NEXT
        return template.format(
            persona=persona,
            artist_context=artist_context,
            current_song=cur_song,
            current_artist=cur_artist,
            prev_line=prev_line,
            cohost_name=cohost_name,
            cohost_label=cohost_label,
        )
