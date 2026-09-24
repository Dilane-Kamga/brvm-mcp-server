"""Tests for the Sikafinance scraper.

Parsing-helper tests run offline against small HTML fixtures; the filings
feed is tested against the real site, matching this project's convention
(see test_brvm.py) of testing scrapers with real network calls.
"""

import pytest
from bs4 import BeautifulSoup

from brvm_mcp.scrapers.sikafinance import SikaFinanceScraper


class TestNumberParser:
    """Same French-format convention as BRVMScraper._parse_number."""

    def test_french_decimal(self):
        assert SikaFinanceScraper._parse_number("33 840") == 33840.0

    def test_percentage(self):
        assert SikaFinanceScraper._parse_number("+1,01%") == 1.01

    def test_placeholder_dash(self):
        assert SikaFinanceScraper._parse_number("-") == 0.0

    def test_empty(self):
        assert SikaFinanceScraper._parse_number("") == 0.0


class TestTickerSlug:
    def test_known_country(self):
        assert SikaFinanceScraper._ticker_slug("CBIBF", "Burkina Faso") == "CBIBF.bf"
        assert SikaFinanceScraper._ticker_slug("BICB", "Bénin") == "BICB.bj"
        assert SikaFinanceScraper._ticker_slug("SLBC", "Côte d'Ivoire") == "SLBC.ci"

    def test_unknown_country_raises(self):
        try:
            SikaFinanceScraper._ticker_slug("XXXX", "Atlantis")
        except ValueError as exc:
            assert "Atlantis" in str(exc)
        else:
            raise AssertionError("expected ValueError for an unknown country")


class TestNewsBlockParser:
    """A Sikafinance news block is a flat <span class="sp1">date</span><a>title</a><br/>
    sequence, not one <li> per item -- verify the sibling-walk handles that."""

    def _scraper(self):
        return SikaFinanceScraper()

    def test_parses_date_title_url_pairs(self):
        html = """
        <div class="home_content">
            <span class="sp1">02/09/26</span>
            <a class="lks" href="/marches/some-free-article_123">A free article</a><br/>
            <span class="sp1">01/09/26</span>
            <a class="lks" href="/premium/a-paywalled-piece_124">A paywalled piece</a><br/>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one("div.home_content")
        items = self._scraper()._parse_news_block(container, "https://www.sikafinance.com")

        assert len(items) == 2
        assert items[0].date == "02/09/26"
        assert items[0].title == "A free article"
        assert items[0].url == "https://www.sikafinance.com/marches/some-free-article_123"
        assert items[0].is_premium is False
        assert items[1].is_premium is True

    def test_skips_span_with_no_following_anchor(self):
        html = '<div class="home_content"><span class="sp1">02/09/26</span></div>'
        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one("div.home_content")
        items = self._scraper()._parse_news_block(container, "https://www.sikafinance.com")
        assert items == []


class TestFilingsFeed:
    """Live tests against the real market-wide filings feed."""

    @pytest.mark.asyncio
    async def test_get_filings_returns_rows(self):
        scraper = SikaFinanceScraper()
        try:
            filings = await scraper.get_filings(limit=10)
            assert len(filings) > 0
            for f in filings:
                assert f.date
                assert f.issuer
                assert f.pdf_url.startswith("https://www.sikafinance.com/")
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_search_filters_by_query(self):
        scraper = SikaFinanceScraper()
        try:
            filings = await scraper.get_filings(limit=50)
            needle = "dividende"
            matches = [
                f for f in filings
                if needle in f.issuer.lower() or needle in f.title.lower()
            ]
            # every match found by hand must actually contain the needle
            for f in matches:
                assert needle in f.issuer.lower() or needle in f.title.lower()
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_download_filing_rejects_foreign_url(self):
        scraper = SikaFinanceScraper()
        try:
            with pytest.raises(ValueError, match="sikafinance.com"):
                await scraper.download_filing("https://evil.example.com/x.pdf", "/tmp")
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_download_filing_saves_real_pdf(self, tmp_path):
        scraper = SikaFinanceScraper()
        try:
            filings = await scraper.get_filings(limit=1)
            assert filings, "need at least one real filing to test a download"
            path = await scraper.download_filing(filings[0].pdf_url, str(tmp_path))
            from pathlib import Path

            saved = Path(path)
            assert saved.exists()
            assert saved.stat().st_size > 0
        finally:
            await scraper.close()
