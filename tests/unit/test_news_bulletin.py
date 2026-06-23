"""Unit tests for MockNewsFetcher, RssNewsFetcher, and NewsBulletinGenerator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.news.bulletin_generator import NewsBulletinGenerator
from src.news.fetcher import MockNewsFetcher, NewsArticle, NewsData, RssNewsFetcher


class TestMockNewsFetcher:
    def test_fetch_returns_news_data(self) -> None:
        fetcher = MockNewsFetcher()
        result = fetcher.fetch()
        assert isinstance(result, NewsData)

    def test_all_fields_are_non_empty(self) -> None:
        fetcher = MockNewsFetcher()
        result = fetcher.fetch()
        assert result.world
        assert result.country
        assert result.local
        assert result.weather
        assert result.articles

    def test_second_call_returns_different_headlines(self) -> None:
        fetcher = MockNewsFetcher()
        first = fetcher.fetch()
        second = fetcher.fetch()
        # At least one field should differ between rotation slots
        assert first.world != second.world

    def test_rotation_wraps_around(self) -> None:
        fetcher = MockNewsFetcher()
        # Fetch more times than there are headlines; should not raise
        results = [fetcher.fetch() for _ in range(9)]
        assert len(results) == 9
        # First and fourth should be the same (3-item rotation)
        assert results[0].world == results[3].world


class TestNewsBulletinGenerator:
    def test_format_returns_non_empty_string(self) -> None:
        news = MockNewsFetcher().fetch()
        script = NewsBulletinGenerator().format(news, 9)
        assert isinstance(script, str)
        assert len(script) > 50

    def test_format_contains_hour_label(self) -> None:
        news = MockNewsFetcher().fetch()
        script = NewsBulletinGenerator().format(news, 9)
        assert "nine" in script

    @pytest.mark.parametrize("hour,expected", [
        (6, "Good morning"),
        (11, "Good morning"),
        (12, "Good afternoon"),
        (17, "Good afternoon"),
        (18, "Good evening"),
        (23, "Good evening"),
        (0, "Good evening"),   # midnight → evening
        (4, "Good evening"),
    ])
    def test_greeting_by_time_of_day(self, hour: int, expected: str) -> None:
        news = MockNewsFetcher().fetch()
        script = NewsBulletinGenerator().format(news, hour)
        assert script.startswith(expected)

    def test_format_ends_with_back_to_music(self) -> None:
        news = MockNewsFetcher().fetch()
        script = NewsBulletinGenerator().format(news, 10)
        assert "back to the music" in script

    def test_format_includes_all_news_sections(self) -> None:
        news = NewsData(
            world="World event here.",
            country="Poland event here.",
            local="Warsaw event here.",
            weather="Sunny skies.",
        )
        script = NewsBulletinGenerator().format(news, 8)
        assert "World event here." in script
        assert "Poland event here." in script
        assert "Warsaw event here." in script
        assert "Sunny skies." in script

    def test_format_omits_weather_section_when_empty(self) -> None:
        news = NewsData(world="W.", country="C.", local="L.", weather="")
        script = NewsBulletinGenerator().format(news, 8)
        assert "weather" not in script.lower()


class TestRssNewsFetcher:
    def _make_fake_feed(self, titles: list[str]) -> dict:
        return {
            "feed": {"title": "Example RSS"},
            "entries": [
                {"title": t, "link": f"https://example.com/{idx}"}
                for idx, t in enumerate(titles)
            ],
        }

    def test_fetch_returns_news_data(self) -> None:
        fetcher = RssNewsFetcher()
        fake = self._make_fake_feed(["Headline A", "Headline B"])
        with patch("feedparser.parse", return_value=fake):
            result = fetcher.fetch()
        assert isinstance(result, NewsData)

    def test_headlines_joined_with_separator(self) -> None:
        fetcher = RssNewsFetcher(max_headlines=2)
        fake = self._make_fake_feed(["First story", "Second story"])
        with patch("feedparser.parse", return_value=fake):
            result = fetcher._fetch_headlines("http://fake.url")
        assert result == "First story / Second story"

    def test_empty_feed_returns_fallback(self) -> None:
        fetcher = RssNewsFetcher()
        with patch("feedparser.parse", return_value={"entries": []}):
            result = fetcher._fetch_headlines("http://fake.url")
        assert "No current headlines" in result

    def test_feed_error_returns_fallback(self) -> None:
        fetcher = RssNewsFetcher()
        with patch("feedparser.parse", side_effect=Exception("network error")):
            result = fetcher._fetch_headlines("http://fake.url")
        assert "No current headlines" in result

    def test_max_headlines_respected(self) -> None:
        fetcher = RssNewsFetcher(max_headlines=1)
        fake = self._make_fake_feed(["Only first", "Ignored second"])
        with patch("feedparser.parse", return_value=fake):
            result = fetcher._fetch_headlines("http://fake.url")
        assert "Only first" in result
        assert "Ignored second" not in result

    def test_weather_field_is_empty_string(self) -> None:
        fetcher = RssNewsFetcher()
        fake = self._make_fake_feed(["Headline"])
        with patch("feedparser.parse", return_value=fake):
            result = fetcher.fetch()
        assert result.weather == ""

    def test_fetch_preserves_article_links(self) -> None:
        fetcher = RssNewsFetcher(max_headlines=1)
        fake = self._make_fake_feed(["Linked headline"])
        with patch("feedparser.parse", return_value=fake):
            result = fetcher.fetch()
        assert isinstance(result.articles[0], NewsArticle)
        assert result.articles[0].title == "Linked headline"
        assert result.articles[0].url == "https://example.com/0"
        assert result.articles[0].source == "Example RSS"
