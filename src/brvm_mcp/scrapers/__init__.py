"""
BRVM Web Scraper
================
Scrapes market data from publicly available BRVM data sources.

Primary source: afx.kwayisi.org/brvm/ (structured HTML, reliable)
Fallback: brvm.org (official, but less scrapable)

Data is cached locally with configurable TTL to be respectful
of source servers and to provide fast responses to MCP tool calls.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup, Tag

from brvm_mcp.models import (
    CompanyInfo,
    IndexValue,
    MarketSummary,
    StockQuote,
    TopMover,
)

logger = logging.getLogger(__name__)

AFX_BASE = "https://afx.kwayisi.org/brvm"
BRVM_BASE = "https://www.brvm.org"

# Known BRVM tickers mapped to (full_name, country, sector)
# This acts as a static enrichment layer; the scraper fills in live prices.
TICKER_REGISTRY: dict[str, tuple[str, str, str]] = {
    "ABJC": ("Abidjan Catering (SCA)", "Côte d'Ivoire", "Distribution"),
    "BICC": ("BICI Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "BNBC": ("Bernabé Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "BOAB": ("Bank of Africa Bénin", "Bénin", "Services Financiers"),
    "BOABF": ("Bank of Africa Burkina Faso", "Burkina Faso", "Services Financiers"),
    "BOAC": ("Bank of Africa Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "BOAN": ("Bank of Africa Niger", "Niger", "Services Financiers"),
    "BOAS": ("Bank of Africa Sénégal", "Sénégal", "Services Financiers"),
    "CABC": ("Sicable Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "CBIBF": ("Coris Bank International", "Burkina Faso", "Services Financiers"),
    "CFAC": ("CFAO Motors Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "CIEC": ("CIE Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "ECOC": ("Ecobank Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "ETIT": ("Ecobank Transnational Inc.", "Togo", "Services Financiers"),
    "FTSC": ("Filtisac Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "NEIC": ("NEI-CEDA Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "NSBC": ("NSIA Banque Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "NTLC": ("Nestlé Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "ONTC": ("Onatel Burkina Faso", "Burkina Faso", "Services Publics"),
    "ORAC": ("Orange Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "PALC": ("Palm Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "PRSC": ("Tractafric Motors Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "SAFC": ("Safca Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "SCRC": ("Sucrivoire", "Côte d'Ivoire", "Agriculture"),
    "SDCC": ("SODE Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "SDSC": ("SDS Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "SEMC": ("Crown SIEM Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SGBC": ("Société Générale CI", "Côte d'Ivoire", "Services Financiers"),
    "SIBC": ("SIB Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "SICC": ("Sicor Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "SLBC": ("Solibra Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SMBC": ("SMB Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SNTS": ("Sonatel Sénégal", "Sénégal", "Services Publics"),
    "SOGC": ("Sogb Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "SPHC": ("SAPH Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "STBC": ("Sitab Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SVOC": ("Movis Côte d'Ivoire", "Côte d'Ivoire", "Transport"),
    "TTLC": ("Total Énergies CI", "Côte d'Ivoire", "Distribution"),
    "TTLS": ("Total Énergies Sénégal", "Sénégal", "Distribution"),
    "UNLC": ("Unilever Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "UNXC": ("Uniwax Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "VIVS": ("Vivo Energy Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
}


class BRVMScraper:
    """Async scraper for BRVM market data."""

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "BRVM-MCP-Server/0.1 "
                    "(+https://github.com/dilanefk/brvm-mcp-server; research use)"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        )

    async def close(self):
        await self._client.aclose()

    # ── Live Quotes ──────────────────────────────────────────────

    async def get_all_quotes(self) -> list[StockQuote]:
        """Scrape all live stock quotes from afx.kwayisi.org/brvm/."""
        resp = await self._client.get(f"{AFX_BASE}/")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        quotes: list[StockQuote] = []
        table = soup.find("table", id="t-shares")
        if not table:
            # Fallback: find the main data table
            table = soup.find("table")
        if not table or not isinstance(table, Tag):
            logger.warning("Could not find shares table on afx page")
            return quotes

        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            ticker_tag = cells[0].find("a")
            ticker = ticker_tag.get_text(strip=True) if ticker_tag else cells[0].get_text(strip=True)
            name_raw = cells[1].get_text(strip=True) if len(cells) > 1 else ""

            # Parse numeric values safely
            price = self._parse_number(cells[2].get_text(strip=True)) if len(cells) > 2 else 0.0
            change_text = cells[3].get_text(strip=True) if len(cells) > 3 else "0"
            volume = int(self._parse_number(cells[4].get_text(strip=True))) if len(cells) > 4 else 0
            value_traded = self._parse_number(cells[5].get_text(strip=True)) if len(cells) > 5 else 0.0

            change_pct = self._parse_number(change_text.replace("%", ""))
            change_abs = price * change_pct / 100 if change_pct else 0.0

            # Enrich from registry
            registry_info = TICKER_REGISTRY.get(ticker, (name_raw, "", ""))

            quotes.append(
                StockQuote(
                    ticker=ticker,
                    name=registry_info[0] or name_raw,
                    price=price,
                    change=round(change_abs, 2),
                    change_pct=change_pct,
                    volume=volume,
                    value_traded=value_traded,
                    previous_close=round(price - change_abs, 2) if change_abs else price,
                    country=registry_info[1],
                    sector=registry_info[2],
                    as_of=datetime.now().isoformat(timespec="minutes"),
                )
            )

        logger.info(f"Scraped {len(quotes)} quotes from AFX")
        return quotes

    async def get_quote(self, ticker: str) -> StockQuote | None:
        """Get a single stock quote by ticker."""
        ticker = ticker.upper().strip()
        quotes = await self.get_all_quotes()
        return next((q for q in quotes if q.ticker == ticker), None)

    # ── Indices ──────────────────────────────────────────────────

    async def get_indices(self) -> list[IndexValue]:
        """Scrape current BRVM index values."""
        resp = await self._client.get(f"{AFX_BASE}/")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        indices: list[IndexValue] = []

        # Look for index data — typically in a summary section or separate table
        # AFX displays indices in a paragraph or small table near the top
        summary_text = soup.get_text()

        # Parse index patterns like "BRVM Composite: 402.52 (+0.67%)"
        index_patterns = [
            ("BRVM Composite", r"BRVM[- ]?C(?:omposite|I)\D*?([\d,.]+)"),
            ("BRVM 30", r"BRVM[- ]?30\D*?([\d,.]+)"),
            ("BRVM Prestige", r"BRVM[- ]?Prestige\D*?([\d,.]+)"),
            ("BRVM Principal", r"BRVM[- ]?Principal\D*?([\d,.]+)"),
        ]

        for name, pattern in index_patterns:
            match = re.search(pattern, summary_text, re.IGNORECASE)
            if match:
                value = self._parse_number(match.group(1))
                # Try to find the change percentage nearby
                change_match = re.search(
                    rf"{re.escape(name)}.*?([+-]?\d+[.,]?\d*)%",
                    summary_text,
                    re.IGNORECASE,
                )
                change_pct = self._parse_number(change_match.group(1)) if change_match else 0.0
                indices.append(
                    IndexValue(
                        name=name,
                        value=value,
                        change=round(value * change_pct / 100, 2),
                        change_pct=change_pct,
                        as_of=datetime.now().isoformat(timespec="minutes"),
                    )
                )

        # If regex approach didn't work, try table-based parsing
        if not indices:
            for table in soup.find_all("table"):
                header_text = table.get_text().lower()
                if "composite" in header_text or "indice" in header_text:
                    for row in table.find_all("tr")[1:]:
                        cells = row.find_all("td")
                        if len(cells) >= 3:
                            idx_name = cells[0].get_text(strip=True)
                            idx_value = self._parse_number(cells[1].get_text(strip=True))
                            idx_change = self._parse_number(
                                cells[2].get_text(strip=True).replace("%", "")
                            )
                            indices.append(
                                IndexValue(
                                    name=idx_name,
                                    value=idx_value,
                                    change_pct=idx_change,
                                    change=round(idx_value * idx_change / 100, 2),
                                    as_of=datetime.now().isoformat(timespec="minutes"),
                                )
                            )
                    break

        logger.info(f"Scraped {len(indices)} indices")
        return indices

    # ── Market Summary ───────────────────────────────────────────

    async def get_market_summary(self) -> MarketSummary:
        """Build a full market summary from scraped data."""
        quotes = await self.get_all_quotes()
        indices = await self.get_indices()

        gainers = [q for q in quotes if q.change_pct > 0]
        losers = [q for q in quotes if q.change_pct < 0]
        unchanged = [q for q in quotes if q.change_pct == 0]

        return MarketSummary(
            date=datetime.now().strftime("%Y-%m-%d"),
            total_volume=sum(q.volume for q in quotes),
            total_value=sum(q.value_traded for q in quotes),
            market_cap=sum(q.market_cap or 0 for q in quotes),
            gainers=len(gainers),
            losers=len(losers),
            unchanged=len(unchanged),
            indices=indices,
        )

    # ── Top Movers ───────────────────────────────────────────────

    async def get_top_movers(self, n: int = 5) -> dict[str, list[TopMover]]:
        """Get top N gainers and losers."""
        quotes = await self.get_all_quotes()
        active = [q for q in quotes if q.volume > 0]

        sorted_up = sorted(active, key=lambda q: q.change_pct, reverse=True)
        sorted_down = sorted(active, key=lambda q: q.change_pct)

        def to_mover(q: StockQuote) -> TopMover:
            return TopMover(
                ticker=q.ticker,
                name=q.name,
                price=q.price,
                change_pct=q.change_pct,
                volume=q.volume,
            )

        return {
            "gainers": [to_mover(q) for q in sorted_up[:n]],
            "losers": [to_mover(q) for q in sorted_down[:n] if q.change_pct < 0],
        }

    # ── Company Info ─────────────────────────────────────────────

    async def get_company_info(self, ticker: str) -> CompanyInfo | None:
        """Get static company info, enriched from registry + live data."""
        ticker = ticker.upper().strip()
        registry = TICKER_REGISTRY.get(ticker)
        if not registry:
            return None

        quote = await self.get_quote(ticker)

        return CompanyInfo(
            ticker=ticker,
            name=registry[0],
            country=registry[1],
            sector=registry[2],
            market_cap=quote.market_cap if quote else None,
        )

    # ── Search ───────────────────────────────────────────────────

    async def search_stocks(
        self,
        query: str = "",
        country: str = "",
        sector: str = "",
    ) -> list[CompanyInfo]:
        """Search tickers by name, country, or sector."""
        results = []
        query_lower = query.lower()
        country_lower = country.lower()
        sector_lower = sector.lower()

        for ticker, (name, ctry, sect) in TICKER_REGISTRY.items():
            if query_lower and query_lower not in name.lower() and query_lower not in ticker.lower():
                continue
            if country_lower and country_lower not in ctry.lower():
                continue
            if sector_lower and sector_lower not in sect.lower():
                continue

            results.append(
                CompanyInfo(
                    ticker=ticker,
                    name=name,
                    country=ctry,
                    sector=sect,
                )
            )

        return results

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _parse_number(text: str) -> float:
        """Parse a number from text, handling French formatting (space separators, commas)."""
        if not text:
            return 0.0
        cleaned = text.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
        cleaned = re.sub(r"[^\d.\-+]", "", cleaned)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
