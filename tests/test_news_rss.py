import unittest

from findart_collector.news_rss import NewsRssCollector, parse_feed_urls, parse_rss


RSS_XML = """<?xml version=\"1.0\"?>
<rss version=\"2.0\"><channel><title>테스트 뉴스</title>
<item><title>첫 기사</title><link>https://news.example/1</link><guid>article-1</guid><description>요약</description><pubDate>Fri, 24 Jul 2026 11:00:00 +0900</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def get(self, url: str, **kwargs: object) -> FakeResponse:
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
        results, errors = NewsRssCollector(["https://good.example/rss", "https://bad.example/rss"], session=FakeSession()).fetch_all()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
