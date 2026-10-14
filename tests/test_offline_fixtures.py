"""Offline tests that run the parsers on saved copies of real/trimmed pages.

Guards against markup drift and parser breakage without requiring network access.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from brvm_mcp.scrapers import BRVMScraper
from brvm_mcp.scrapers.sikafinance import SikaFinanceScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def brvm_home_html() -> str:
    return (FIXTURES_DIR / "brvm_home.html").read_text(encoding="utf-8")


@pytest.fixture
def sample_boc_bytes() -> bytes:
    return (FIXTURES_DIR / "sample_boc.pdf").read_bytes()


@pytest.fixture
def sikafinance_stock_html() -> str:
    return (FIXTURES_DIR / "sikafinance_stock.html").read_text(encoding="utf-8")


@pytest.fixture
def sikafinance_news_html() -> str:
    return (FIXTURES_DIR / "sikafinance_news.html").read_text(encoding="utf-8")


class TestOfflineBrvmScraper:
    """Offline parsing tests for brvm.org homepage and BOC PDF."""

    @pytest.mark.asyncio
    async def test_offline_brvm_home_parsing(self, brvm_home_html: str):
        scraper = BRVMScraper()
        mock_resp = httpx.Response(
            status_code=200,
            text=brvm_home_html,
            request=httpx.Request("GET", "https://www.brvm.org/"),
        )
        scraper._get_with_retry = AsyncMock(return_value=mock_resp)

        snapshot = await scraper._get_brvm_org_homepage()
        await scraper.close()

        assert snapshot.as_of == "14/10/2026 15:30:00"
        assert snapshot.quotes["SNTS"] == (21500.0, 1.42)
        assert snapshot.quotes["ETIT"] == (18.0, 0.0)
        assert snapshot.quotes["ECOC"] == (7200.0, -0.50)

        assert snapshot.indices["BRVM Composite"] == (285.40, 0.35)
        assert snapshot.indices["BRVM 30"] == (142.10, 0.28)
        assert snapshot.indices["BRVM Prestige"] == (118.75, -0.15)

        assert snapshot.total_value == 1250000000.0
        assert snapshot.market_cap == 9850000000000.0

    def test_offline_boc_pdf_parsing(self, sample_boc_bytes: bytes):
        snapshot = BRVMScraper._parse_boc_pdf(sample_boc_bytes)

        assert snapshot.bulletin_date == "mardi 14 octobre 2026"
        assert snapshot.index_ytd["BRVM Composite"] == 12.45
        assert snapshot.index_ytd["BRVM 30"] == 8.30
        assert snapshot.index_ytd["BRVM Prestige"] == 5.10

        assert snapshot.principal is not None
        assert snapshot.principal.name == "BRVM Principal"
        assert snapshot.principal.value == 120.50
        assert snapshot.principal.change_pct == 1.25
        assert snapshot.principal.ytd_change_pct == 4.50
        assert snapshot.principal.as_of == "mardi 14 octobre 2026"

        assert snapshot.volumes["SNTS"] == 15000
        assert snapshot.volumes["ETIT"] == 100000
        assert snapshot.volumes["ECOC"] == 5400


class TestOfflineSikafinanceScraper:
    """Offline parsing tests for Sikafinance ticker pages and news feeds."""

    @pytest.mark.asyncio
    async def test_offline_sikafinance_stock_page(self, sikafinance_stock_html: str):
        scraper = SikaFinanceScraper()
        mock_resp = httpx.Response(
            status_code=200,
            text=sikafinance_stock_html,
            request=httpx.Request("GET", "https://www.sikafinance.com/marches/cotation_SNTS.sn"),
        )
        scraper._get = AsyncMock(return_value=mock_resp)

        page = await scraper.get_stock_page("SNTS", "Sénégal")
        await scraper.close()

        assert page is not None
        assert page.ticker == "SNTS"
        assert page.name == "SONATEL SENEGAL"
        assert page.isin == "SN0000000001"
        assert page.price == 21500.0
        assert page.change_pct == 1.42
        assert page.volume == 12500
        assert page.value_traded == 268750000.0
        assert page.open == 21200.0
        assert page.high == 21500.0
        assert page.low == 21200.0
        assert page.previous_close == 21200.0
        assert page.beta_1y == 0.85
        assert page.rsi == 58.40
        assert page.capital_exchanged_pct == 0.01
        assert page.market_cap == 2150000000000.0

        assert len(page.historical_ranges) == 2
        assert page.historical_ranges[0].period == "1 an"
        assert page.historical_ranges[0].high == 22000.0
        assert page.historical_ranges[0].low == 17500.0
        assert page.historical_ranges[0].change_pct == 18.50

        assert len(page.dividends) == 2
        assert page.dividends[0].year == "2025"
        assert page.dividends[0].amount == 1500.0
        assert page.dividends[0].yield_pct == 6.98

        assert len(page.recent_news) == 2
        assert page.recent_news[0].title == "Sonatel affiche de solides performances au T3 2026"
        assert page.recent_news[0].is_premium is False
        assert page.recent_news[1].is_premium is True

        assert page.sentiment is not None
        assert page.sentiment.buy_votes == 12
        assert page.sentiment.sell_votes == 2
        assert page.sentiment.hold_votes == 4

    @pytest.mark.asyncio
    async def test_offline_sikafinance_news_feed(self, sikafinance_news_html: str):
        scraper = SikaFinanceScraper()
        mock_resp = httpx.Response(
            status_code=200,
            text=sikafinance_news_html,
            request=httpx.Request("GET", "https://www.sikafinance.com/marches/news_valeur?s=SNTS.sn"),
        )
        scraper._get = AsyncMock(return_value=mock_resp)

        items = await scraper.get_news("SNTS", "Sénégal")
        await scraper.close()

        assert len(items) == 3
        assert items[0].date == "14/10/26"
        assert items[0].title == "Sonatel : progression de 8% du chiffre d'affaires"
        assert items[0].is_premium is False
        assert items[1].is_premium is True
        assert items[2].is_premium is False
