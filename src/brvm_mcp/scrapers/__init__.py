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

import asyncio
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
    "ABJC": ("Servair Abidjan Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "BICB": ("BIIC Bénin", "Bénin", "Services Financiers"),
    "BICC": ("BICI Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "BNBC": ("Bernabé Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "BOAB": ("Bank of Africa Bénin", "Bénin", "Services Financiers"),
    "BOABF": ("Bank of Africa Burkina Faso", "Burkina Faso", "Services Financiers"),
    "BOAC": ("Bank of Africa Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "BOAM": ("Bank of Africa Mali", "Mali", "Services Financiers"),
    "BOAN": ("Bank of Africa Niger", "Niger", "Services Financiers"),
    "BOAS": ("Bank of Africa Sénégal", "Sénégal", "Services Financiers"),
    "CABC": ("Sicable Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "CBIBF": ("Coris Bank International", "Burkina Faso", "Services Financiers"),
    "CFAC": ("CFAO Motors Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "CIEC": ("CIE Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "ECOC": ("Ecobank Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "ETIT": ("Ecobank Transnational Inc.", "Togo", "Services Financiers"),
    "FTSC": ("Filtisac Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "LNBB": ("Loterie Nationale du Bénin", "Bénin", "Distribution"),
    "NEIC": ("NEI-CEDA Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "NSBC": ("NSIA Banque Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "NTLC": ("Nestlé Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "ONTBF": ("Onatel Burkina Faso", "Burkina Faso", "Services Publics"),
    "ORAC": ("Orange Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "ORGT": ("Oragroup Togo", "Togo", "Services Financiers"),
    "PALC": ("Palm Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "PRSC": ("Tractafric Motors Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "SAFC": ("Safca Côte d'Ivoire", "Côte d'Ivoire", "Services Financiers"),
    "SCRC": ("Sucrivoire Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "SDCC": ("SODE Côte d'Ivoire", "Côte d'Ivoire", "Services Publics"),
    "SDSC": ("Bolloré Transport & Logistics", "Côte d'Ivoire", "Transport"),
    "SEMC": ("Eviosys Packaging SIEM", "Côte d'Ivoire", "Industrie"),
    "SGBC": ("Société Générale CI", "Côte d'Ivoire", "Services Financiers"),
    "SHEC": ("Vivo Energy Côte d'Ivoire", "Côte d'Ivoire", "Distribution"),
    "SIBC": ("Société Ivoirienne de Banque", "Côte d'Ivoire", "Services Financiers"),
    "SICC": ("Sicor Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "SIVC": ("Air Liquide Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SLBC": ("Solibra Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SMBC": ("SMB Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "SNTS": ("Sonatel Sénégal", "Sénégal", "Services Publics"),
    "SOGC": ("Sogb Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "SPHC": ("SAPH Côte d'Ivoire", "Côte d'Ivoire", "Agriculture"),
    "STAC": ("Setao Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "STBC": ("Sitab Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "TTLC": ("Total Énergies CI", "Côte d'Ivoire", "Distribution"),
    "TTLS": ("Total Énergies Sénégal", "Sénégal", "Distribution"),
    "UNLC": ("Unilever Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
    "UNXC": ("Uniwax Côte d'Ivoire", "Côte d'Ivoire", "Industrie"),
}


class BRVMScraper:
    """Async scraper for BRVM market data."""

    MAX_RETRIES = 3
    RETRY_BACKOFF = (1.0, 2.0, 4.0)

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

    async def _get_with_retry(self, url: str) -> httpx.Response:
        """GET with exponential backoff on 429/5xx."""
        for attempt in range(self.MAX_RETRIES):
            resp = await self._client.get(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BACKOFF[attempt]
                    logger.warning(f"HTTP {resp.status_code} on {url}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
            resp.raise_for_status()
            return resp
        return resp  # unreachable, but satisfies type checker

    async def close(self):
        await self._client.aclose()

    # ── Live Quotes ──────────────────────────────────────────────

    async def get_all_quotes(self) -> list[StockQuote]:
        """Scrape all live stock quotes from afx.kwayisi.org/brvm/."""
        resp = await self._get_with_retry(f"{AFX_BASE}/")
        soup = BeautifulSoup(resp.text, "lxml")

        quotes: list[StockQuote] = []

        # The stock table is inside <div class="t"> with columns:
        # Ticker | Name | Volume | Price | Change (absolute)
        wrapper = soup.find("div", class_="t")
        table = wrapper.find("table") if wrapper else None
        if not table or not isinstance(table, Tag):
            logger.warning("Could not find shares table on afx page")
            return quotes

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            ticker_tag = cells[0].find("a")
            ticker = ticker_tag.get_text(strip=True) if ticker_tag else cells[0].get_text(strip=True)
            name_raw = cells[1].get_text(strip=True)

            volume = int(self._parse_number(cells[2].get_text(strip=True)))
            price = self._parse_number(cells[3].get_text(strip=True))
            change_abs = self._parse_number(cells[4].get_text(strip=True))

            previous_close = price - change_abs
            change_pct = round((change_abs / previous_close) * 100, 2) if previous_close else 0.0

            registry_info = TICKER_REGISTRY.get(ticker, (name_raw, "", ""))

            quotes.append(
                StockQuote(
                    ticker=ticker,
                    name=registry_info[0] or name_raw,
                    price=price,
                    change=change_abs,
                    change_pct=change_pct,
                    volume=volume,
                    previous_close=round(previous_close, 2),
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
        resp = await self._get_with_retry(f"{AFX_BASE}/")
        soup = BeautifulSoup(resp.text, "lxml")
        now = datetime.now().isoformat(timespec="minutes")

        indices: list[IndexValue] = []

        # 1) BRVM-CI from the summary table at top:
        #    <th>BRVM-CI Index | Year-to-Date | Market Cap.
        #    <td>402.59 (+0.59) | +56.84 (16.44%) | XOF 15.51Tr
        for table in soup.find_all("table"):
            th = table.find("th")
            if th and "BRVM-CI" in th.get_text():
                cells = table.find_all("td")
                if len(cells) >= 2:
                    ci_text = cells[0].get_text(strip=True)
                    ytd_text = cells[1].get_text(strip=True)
                    val_m = re.match(r"([\d.,]+)", ci_text)
                    chg_m = re.search(r"\(([+-]?[\d.,]+)\)", ci_text)
                    ytd_m = re.search(r"\(([\d.,]+)%\)", ytd_text)
                    if val_m:
                        value = self._parse_number(val_m.group(1))
                        change = self._parse_number(chg_m.group(1)) if chg_m else 0.0
                        change_pct = round((change / (value - change)) * 100, 2) if (value - change) else 0.0
                        ytd_pct = self._parse_number(ytd_m.group(1)) if ytd_m else None
                        indices.append(IndexValue(
                            name="BRVM Composite",
                            value=value,
                            change=change,
                            change_pct=change_pct,
                            ytd_change_pct=ytd_pct,
                            as_of=now,
                        ))
                break

        # 2) Other indices from the trading summary paragraph:
        #    "BRVM 30 (+0.17%; +1.3% 1WK; +14.18% YTD)"
        full_text = soup.get_text()
        other_patterns = [
            ("BRVM 30", r"BRVM\s*30\s*\(([+-]?[\d.,]+)%.*?([\d.,]+)%\s*YTD\)"),
            ("BRVM Prestige", r"BRVM\s*Prestige\s*\(([+-]?[\d.,]+)%.*?([\d.,]+)%\s*YTD\)"),
            ("BRVM Principal", r"BRVM\s*Principal\s*\(([+-]?[\d.,]+)%.*?([\d.,]+)%\s*YTD\)"),
        ]
        for name, pattern in other_patterns:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                change_pct = self._parse_number(m.group(1))
                ytd_pct = self._parse_number(m.group(2))
                indices.append(IndexValue(
                    name=name,
                    value=0.0,
                    change_pct=change_pct,
                    ytd_change_pct=ytd_pct,
                    as_of=now,
                ))

        logger.info(f"Scraped {len(indices)} indices")
        return indices

    # ── Market Summary ───────────────────────────────────────────

    async def get_market_summary(self) -> MarketSummary:
        """Build a full market summary from scraped data."""
        resp = await self._get_with_retry(f"{AFX_BASE}/")
        soup = BeautifulSoup(resp.text, "lxml")

        quotes = await self.get_all_quotes()
        indices = await self.get_indices()

        gainers = [q for q in quotes if q.change_pct > 0]
        losers = [q for q in quotes if q.change_pct < 0]
        unchanged = [q for q in quotes if q.change_pct == 0]

        # Parse market cap from the summary table ("XOF 15.51Tr")
        market_cap = 0.0
        for table in soup.find_all("table"):
            th = table.find("th")
            if th and "BRVM-CI" in th.get_text():
                cells = table.find_all("td")
                if len(cells) >= 3:
                    cap_text = cells[2].get_text(strip=True)
                    cap_m = re.search(r"([\d.,]+)\s*Tr", cap_text)
                    if cap_m:
                        market_cap = self._parse_number(cap_m.group(1)) * 1e12
                break

        # Parse total volume/value from trading summary paragraph
        full_text = soup.get_text()
        total_volume = sum(q.volume for q in quotes)
        total_value = 0.0
        val_m = re.search(r"XOF\s*([\d,. ]+)", full_text)
        if val_m:
            total_value = self._parse_number(val_m.group(1))

        return MarketSummary(
            date=datetime.now().strftime("%Y-%m-%d"),
            total_volume=total_volume,
            total_value=total_value,
            market_cap=market_cap,
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
        """Parse a number handling both English (1,234.56) and French (1 234,56) formatting."""
        if not text:
            return 0.0
        cleaned = text.strip().replace("\xa0", "").replace(" ", "")
        cleaned = re.sub(r"[^\d.,\-+]", "", cleaned)
        if not cleaned or cleaned in ("+", "-", ".", ","):
            return 0.0
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+", cleaned):
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
