import unittest

from findart_collector.news_rss import FeedResult, NewsItem, NewsRssCollector, interleave_feed_items, parse_feed_urls, parse_rss


RSS_XML = """<?xml version=\"1.0\"?>
<rss version=\"2.0\"><channel><title>테스트 뉴스</title>
<item><title>첫 기사</title><link>https://news.example/1</link><guid>article-1</guid><description>요약</description><pubDate>Fri, 24 Jul 2026 11:00:00 +0900</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self) -> None:
        self.urls = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.urls.append(url)
        if url == "https://bad.example/rss":
            raise ValueError("broken feed")
        return FakeResponse(RSS_XML)


class NewsRssTests(unittest.TestCase):
    def test_parses_distinct_feed_urls(self):
        self.assertEqual(parse_feed_urls(" https://a.example/rss,https://b.example/rss,https://a.example/rss "), ["https://a.example/rss", "https://b.example/rss"])

    def test_parses_rss_item(self):
        result = parse_rss(RSS_XML, "https://news.example/rss")
        self.assertEqual(result.source, "테스트 뉴스")
        self.assertEqual(result.items[0].external_id, "article-1")
        self.assertEqual(result.items[0].title, "첫 기사")

    def test_continues_when_one_feed_fails(self):
        session = FakeSession()
        urls = ["https://first.example/rss", "https://bad.example/rss", "https://second.example/rss"]

        results, errors = NewsRssCollector(urls, session=session).fetch_all()

        self.assertEqual(session.urls, urls)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(errors), 1)

    def test_uses_response_bytes_to_preserve_feed_encoding(self):
        session = FakeSession()

        results, errors = NewsRssCollector(["https://good.example/rss"], session=session).fetch_all()

        self.assertFalse(errors)
        self.assertEqual(results[0].items[0].title, "첫 기사")

    def test_interleaves_sources_and_removes_duplicate_urls(self):
        first = NewsItem("첫 매체", "https://first.example/rss", "1", "첫 기사", "https://news.example/1", "", None)
        duplicate = NewsItem("둘째 매체", "https://second.example/rss", "duplicate", "중복 기사", first.url, "", None)
        second = NewsItem("첫 매체", "https://first.example/rss", "2", "둘째 기사", "https://news.example/2", "", None)
        third = NewsItem("둘째 매체", "https://second.example/rss", "3", "셋째 기사", "https://news.example/3", "", None)

        items = interleave_feed_items(
            [
                FeedResult("첫 매체", first.source_url, [first, second]),
                FeedResult("둘째 매체", duplicate.source_url, [duplicate, third]),
            ]
        )

        self.assertEqual([item.external_id for item in items], ["1", "2", "3"])
