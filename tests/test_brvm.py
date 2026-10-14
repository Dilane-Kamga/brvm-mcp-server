"""Tests for BRVM scraper and MCP tools."""


import pytest

from brvm_mcp.scrapers import TICKER_REGISTRY, BRVMScraper


class TestTickerRegistry:
    """Test the static ticker registry."""

    def test_registry_not_empty(self):
        assert len(TICKER_REGISTRY) > 30

    def test_all_entries_have_three_fields(self):
        for ticker, info in TICKER_REGISTRY.items():
            assert len(info) == 3, f"{ticker} has {len(info)} fields, expected 3"
            name, country, sector = info
            assert name, f"{ticker} has empty name"
            assert country, f"{ticker} has empty country"
            assert sector, f"{ticker} has empty sector"

    def test_known_tickers_exist(self):
        assert "SNTS" in TICKER_REGISTRY  # Sonatel
        assert "SGBC" in TICKER_REGISTRY  # Société Générale CI
        assert "ETIT" in TICKER_REGISTRY  # Ecobank Transnational
        assert "ORAC" in TICKER_REGISTRY  # Orange CI

    def test_countries_are_uemoa(self):
        valid_countries = {
            "Bénin", "Burkina Faso", "Côte d'Ivoire", "Guinée-Bissau",
            "Mali", "Niger", "Sénégal", "Togo",
        }
        for ticker, (_, country, _) in TICKER_REGISTRY.items():
            assert country in valid_countries, f"{ticker} has invalid country: {country}"


class TestNumberParser:
    """Test the French-format number parser."""

    def test_simple_integer(self):
        assert BRVMScraper._parse_number("1234") == 1234.0

    def test_french_decimal(self):
        assert BRVMScraper._parse_number("1 234,56") == 1234.56

    def test_negative(self):
        assert BRVMScraper._parse_number("-3,14") == -3.14

    def test_percentage(self):
        assert BRVMScraper._parse_number("+2.5%") == 2.5

    def test_empty(self):
        assert BRVMScraper._parse_number("") == 0.0

    def test_non_numeric(self):
        assert BRVMScraper._parse_number("N/A") == 0.0

    def test_nbsp(self):
        assert BRVMScraper._parse_number("15\xa0000") == 15000.0

    def test_english_thousands(self):
        assert BRVMScraper._parse_number("3,262") == 3262.0
        assert BRVMScraper._parse_number("1,018,483") == 1018483.0
        assert BRVMScraper._parse_number("-1,330") == -1330.0

    def test_mixed_format(self):
        assert BRVMScraper._parse_number("1,234.56") == 1234.56


class TestSearchStocks:
    """Test the stock search functionality."""

    @pytest.mark.asyncio
    async def test_search_by_country(self):
        scraper = BRVMScraper()
        results = await scraper.search_stocks(country="Sénégal")
        assert len(results) > 0
        for r in results:
            assert "Sénégal" in r.country
        await scraper.close()

    @pytest.mark.asyncio
    async def test_search_by_sector(self):
        scraper = BRVMScraper()
        results = await scraper.search_stocks(sector="Services Financiers")
        assert len(results) > 5  # BRVM has many banks
        await scraper.close()

    @pytest.mark.asyncio
    async def test_search_by_name(self):
        scraper = BRVMScraper()
        results = await scraper.search_stocks(query="ecobank")
        assert len(results) >= 2  # ECOC + ETIT at minimum
        await scraper.close()

    @pytest.mark.asyncio
    async def test_search_empty_filters_error(self):
        scraper = BRVMScraper()
        results = await scraper.search_stocks()
        # Empty search returns all
        assert len(results) == len(TICKER_REGISTRY)
        await scraper.close()


class TestVolumeAsOf:
    """Test that volume_as_of is populated from BOC snapshot in MarketSummary and StockQuote."""

    def test_models_have_volume_as_of_field(self):
        from brvm_mcp.models import MarketSummary, StockQuote

        quote = StockQuote(
            ticker="SNTS",
            name="Sonatel",
            price=15000.0,
            volume=500,
            volume_as_of="mardi 13 octobre 2026",
        )
        assert quote.volume_as_of == "mardi 13 octobre 2026"

        summary = MarketSummary(
            date="2026-10-14",
            total_volume=12000,
            volume_as_of="mardi 13 octobre 2026",
            total_value=500000000.0,
            market_cap=9000000000.0,
        )
        assert summary.volume_as_of == "mardi 13 octobre 2026"

    @pytest.mark.asyncio
    async def test_get_market_summary_populates_volume_as_of(self):
        from unittest.mock import AsyncMock

        from brvm_mcp.scrapers import _BocSnapshot, _BrvmOrgSnapshot

        scraper = BRVMScraper()
        boc_mock = _BocSnapshot(
            bulletin_date="13/10/2026",
            index_ytd={},
            principal=None,
            volumes={"SNTS": 100},
        )
        homepage_mock = _BrvmOrgSnapshot(
            as_of="14/10/2026 - 15:00",
            quotes={"SNTS": (15000.0, 1.5)},
            indices={},
            market_cap=1000000.0,
            total_value=50000.0,
        )

        scraper._get_brvm_org_homepage = AsyncMock(return_value=homepage_mock)
        scraper._get_latest_boc_snapshot = AsyncMock(return_value=boc_mock)

        try:
            summary = await scraper.get_market_summary()
            assert summary.volume_as_of == "13/10/2026"
            assert summary.total_volume == 100

            quotes = await scraper.get_all_quotes()
            assert len(quotes) == 1
            assert quotes[0].volume_as_of == "13/10/2026"
            assert quotes[0].volume == 100
        finally:
            await scraper.close()
