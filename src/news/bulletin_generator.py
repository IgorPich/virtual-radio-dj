"""News bulletin script generator — template-based, no LLM."""

from __future__ import annotations

from src.news.fetcher import NewsData


def _greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


def _hour_label(hour: int) -> str:
    """Return a spoken time string, e.g. 'nine o'clock' / 'midnight'."""
    labels = [
        "midnight", "one", "two", "three", "four", "five",
        "six", "seven", "eight", "nine", "ten", "eleven",
        "noon", "one", "two", "three", "four", "five",
        "six", "seven", "eight", "nine", "ten", "eleven",
    ]
    return labels[hour % 24]


class NewsBulletinGenerator:
    """
    Formats a :class:`NewsData` object into broadcast-ready spoken text.

    Deliberately uses a string template rather than the LLM so that news
    airs instantly at the top of the hour without the latency of an inference
    call.
    """

    def format(self, news: NewsData, hour: int) -> str:
        """
        Build a full spoken news bulletin.

        Args:
            news: Structured news content from the fetcher.
            hour: Current hour (0–23), used for greeting and time reference.

        Returns:
            A complete, broadcast-ready spoken script string.
        """
        greeting = _greeting(hour)
        time_label = _hour_label(hour)

        weather_part = (
            f"\n\nA quick look at the weather: {news.weather} "
            if news.weather
            else ""
        )

        return (
            f"{greeting}, listeners. It's {time_label} o'clock, "
            f"and here's your Midnight Radio news update. "
            f"\n\n"
            f"In world news: {news.world} "
            f"\n\n"
            f"Here in Poland: {news.country} "
            f"\n\n"
            f"And closer to home in Warsaw: {news.local} "
            f"{weather_part}"
            f"\n\n"
            f"That's your {time_label} o'clock bulletin. "
            f"Now, back to the music."
        )
