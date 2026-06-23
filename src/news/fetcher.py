"""News data fetcher — mock and live RSS implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

import feedparser

from src.utils.logger import get_logger

_logger = get_logger("news.fetcher")

_NO_HEADLINES = "No current headlines available."


@dataclass
class NewsArticle:
    """Readable article metadata shown in the web UI."""

    title: str
    url: str
    source: str
    category: str


@dataclass
class NewsData:
    """Structured news content for a single bulletin."""

    world: str
    country: str   # Poland
    local: str     # Warsaw
    weather: str
    articles: list[NewsArticle] = field(default_factory=list)


class MockNewsFetcher:
    """
    Returns plausible but hardcoded news data.
    Used in tests and as a development fallback.
    """

    _WORLD_HEADLINES = [
        "Global leaders are meeting in Geneva to discuss international climate targets, "
        "with several nations pledging new carbon-reduction commitments.",
        "Diplomatic talks between major world powers resume today amid calls for "
        "renewed cooperation on trade and security.",
        "A landmark agreement on digital infrastructure has been signed by over forty "
        "countries, aiming to close the global connectivity gap.",
    ]
    _POLAND_HEADLINES = [
        "The Polish parliament is debating new infrastructure investment proposals "
        "worth over fifteen billion zlotys, focused on rail upgrades across the country.",
        "Poland's economy grew by two-point-eight percent in the last quarter, "
        "outpacing most of its European neighbours.",
        "A major renewable energy project in Mazovia is set to provide clean power "
        "to over two hundred thousand households by next year.",
    ]
    _WARSAW_HEADLINES = [
        "Warsaw's city council has approved a new cycling network expanding plan, "
        "adding fifty kilometres of protected lanes before the end of the year.",
        "The Warsaw metro line extension opened its first new station today, "
        "cutting commute times for thousands of residents in the Wola district.",
        "Outdoor markets across Warsaw are reporting record visitor numbers "
        "this spring as residents embrace the warmer weather.",
    ]
    _WEATHER_LINES = [
        "Expect partly cloudy skies today with temperatures around fourteen degrees "
        "and light winds from the west. Tomorrow looks brighter.",
        "It's a cool but dry day in Warsaw — highs of twelve degrees this afternoon, "
        "dropping to six overnight. No rain expected until the weekend.",
        "A warm front is moving in from the south — temperatures climbing to seventeen "
        "degrees by midday with plenty of sunshine and just a light breeze.",
    ]

    def __init__(self) -> None:
        self._call_count = 0

    def fetch(self) -> NewsData:
        """Return the next set of mock headlines, cycling through the lists."""
        idx = self._call_count % len(self._WORLD_HEADLINES)
        self._call_count += 1
        return NewsData(
            world=self._WORLD_HEADLINES[idx],
            country=self._POLAND_HEADLINES[idx],
            local=self._WARSAW_HEADLINES[idx],
            weather=self._WEATHER_LINES[idx],
            articles=[
                NewsArticle(
                    title="Mock world briefing",
                    url="https://example.com/world",
                    source="Mock News",
                    category="world",
                ),
                NewsArticle(
                    title="Mock Poland briefing",
                    url="https://example.com/poland",
                    source="Mock News",
                    category="country",
                ),
                NewsArticle(
                    title="Mock Warsaw briefing",
                    url="https://example.com/warsaw",
                    source="Mock News",
                    category="local",
                ),
            ],
        )


class RssNewsFetcher:
    """
    Fetches live news headlines via RSS using feedparser.

    Calls are synchronous and designed to run inside
    ``asyncio.get_running_loop().run_in_executor()`` so they don't block the
    event loop.  Falls back to ``_NO_HEADLINES`` if a feed is unreachable or
    returns no entries.

    Args:
        world_feed_url:   RSS feed for world news. Defaults to BBC World.
        poland_feed_url:  RSS feed for Polish national news. Defaults to RMF24.
        warsaw_feed_url:  RSS feed for Warsaw/local news. Defaults to TVN24.
        max_headlines:    Number of top headlines to pull from each feed (2–3).
    """

    DEFAULT_WORLD_FEED = "https://feeds.bbci.co.uk/news/world/rss.xml"
    DEFAULT_POLAND_FEED = "https://www.rmf24.pl/rss.xml"
    DEFAULT_WARSAW_FEED = "https://tvn24.pl/wiadomosci-z-kraju,3.xml"

    def __init__(
        self,
        world_feed_url: str = DEFAULT_WORLD_FEED,
        poland_feed_url: str = DEFAULT_POLAND_FEED,
        warsaw_feed_url: str = DEFAULT_WARSAW_FEED,
        max_headlines: int = 2,
    ) -> None:
        self._world_feed_url = world_feed_url
        self._poland_feed_url = poland_feed_url
        self._warsaw_feed_url = warsaw_feed_url
        self._max_headlines = max_headlines

    def fetch(self) -> NewsData:
        """Fetch current headlines from all configured RSS feeds."""
        world_articles = self._fetch_articles(self._world_feed_url, "world")
        country_articles = self._fetch_articles(self._poland_feed_url, "country")
        local_articles = self._fetch_articles(self._warsaw_feed_url, "local")
        world = self._headlines_from_articles(world_articles)
        country = self._headlines_from_articles(country_articles)
        local = self._headlines_from_articles(local_articles)
        # Weather requires a dedicated API key; the bulletin omits the section
        # when this field is empty.
        return NewsData(
            world=world,
            country=country,
            local=local,
            weather="",
            articles=[*world_articles, *country_articles, *local_articles],
        )

    def _fetch_headlines(self, url: str) -> str:
        """
        Parse *url* with feedparser and return the top headlines joined by " / ".

        Returns ``_NO_HEADLINES`` if the feed is empty or an error occurs.
        """
        return self._headlines_from_articles(self._fetch_articles(url, ""))

    def _fetch_articles(self, url: str, category: str) -> list[NewsArticle]:
        """Parse *url* with feedparser and return displayable article links."""
        try:
            feed = feedparser.parse(url)
            articles: list[NewsArticle] = []
            for entry in (feed.get("entries") or [])[: self._max_headlines]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                link = entry.get("link", "").strip()
                articles.append(
                    NewsArticle(
                        title=title,
                        url=link,
                        source=self._source_name(feed, link or url),
                        category=category,
                    )
                )
            if not articles:
                _logger.warning("RSS feed returned no entries: %s", url)
            else:
                _logger.debug("RSS fetched %d headline(s) from %s", len(articles), url)
            return articles
        except Exception as exc:
            _logger.warning("RSS fetch failed for %s: %s", url, exc)
            return []

    @staticmethod
    def _headlines_from_articles(articles: list[NewsArticle]) -> str:
        titles = [article.title for article in articles if article.title]
        return " / ".join(titles) if titles else _NO_HEADLINES

    @staticmethod
    def _source_name(feed: dict, fallback_url: str) -> str:
        feed_title = (feed.get("feed") or {}).get("title", "").strip()
        if feed_title:
            return feed_title
        host = urlparse(fallback_url).netloc.replace("www.", "")
        return host or "RSS"
