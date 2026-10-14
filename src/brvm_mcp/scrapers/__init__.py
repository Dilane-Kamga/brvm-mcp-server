"""
BRVM Web Scraper
================
Scrapes market data straight from the exchange's own site, brvm.org:

- Homepage ticker tape + "Activités du marché" widget: same-day price,
  change %, market cap, transaction value (real-time-ish, dated).
- Daily "Bulletin Officiel de la Cote" (BOC) PDF: per-stock volume, index
  YTD %, and the BRVM Principal index — none of which brvm.org's homepage
  exposes. The BOC itself lags one trading session (published after the
  next session's data would otherwise be needed), same as any other
  source we found for these fields — so this is not a freshness problem,
  it's the nature of the data.

Historically this scraper used afx.kwayisi.org as its primary source, with
brvm.org as an unused "fallback" in name only. kwayisi turned out to lag a
full session on everything AND to have real uptime problems, so it was
dropped entirely in favor of consolidating on the official site.

Data is cached locally with configurable TTL to be respectful of source
servers and to provide fast responses to MCP tool calls.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import pdfplumber
from bs4 import BeautifulSoup, Tag

from brvm_mcp.models import (
    CompanyInfo,
    IndexValue,
    MarketSummary,
    StockQuote,
    TopMover,
)

logger = logging.getLogger(__name__)

BRVM_BASE = "https://www.brvm.org"
BOC_LIST_URL = f"{BRVM_BASE}/fr/bulletins-officiels-de-la-cote"
BOC_CACHE_TTL = 3600.0  # the BOC only changes once a day; no need to re-download every call

INDEX_NAMES = ("BRVM Composite", "BRVM 30", "BRVM Prestige")


@dataclass
class _BrvmOrgSnapshot:
    """One parsed brvm.org homepage fetch — the same-day, real-time-ish source."""

    as_of: str
    # ticker -> (price, change_pct)
    quotes: dict[str, tuple[float, float]] = field(default_factory=dict)
    # name -> (value, change_pct)
    indices: dict[str, tuple[float, float]] = field(default_factory=dict)
    market_cap: float = 0.0
    total_value: float = 0.0


@dataclass
class _BocSnapshot:
    """One parsed Bulletin Officiel de la Cote PDF — the lagging, once-a-day source."""

    bulletin_date: str  # as printed in the PDF, e.g. "mardi 15 septembre 2026"
    # name -> YTD % for the 3 brvm.org-covered indices
    index_ytd: dict[str, float] = field(default_factory=dict)
    # BRVM Principal has no brvm.org homepage equivalent at all
    principal: IndexValue | None = None
    volumes: dict[str, int] = field(default_factory=dict)  # ticker -> shares traded


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
    """Async scraper for BRVM market data, sourced entirely from brvm.org."""

    MAX_RETRIES = 3
    RETRY_BACKOFF = (1.0, 2.0, 4.0)

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "BRVM-MCP-Server/0.1 "
                    "(+https://github.com/Dilane-Kamga/brvm-mcp-server; research use)"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        )
        self._boc_cache: tuple[float, _BocSnapshot] | None = None

    async def _get_with_retry(self, url: str) -> httpx.Response:
        """GET with exponential backoff on 429/5xx and connection-level failures
        (timeout, DNS, refused) — a dead host used to raise straight away."""
        last_exc: httpx.TransportError | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.get(url)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BACKOFF[attempt]
                    logger.warning(f"{type(exc).__name__} on {url}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BACKOFF[attempt]
                    logger.warning(f"HTTP {resp.status_code} on {url}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
            resp.raise_for_status()
            return resp
        if last_exc:
            raise last_exc
        return resp  # unreachable, but satisfies type checker

    async def close(self):
        await self._client.aclose()

    # ── brvm.org homepage (same-day) ────────────────────────────────

    async def _get_brvm_org_homepage(self) -> _BrvmOrgSnapshot:
        """Fetch and parse brvm.org's homepage: ticker tape, indices, market activity."""
        resp = await self._get_with_retry(f"{BRVM_BASE}/")
        soup = BeautifulSoup(resp.text, "lxml")

        as_of = ""
        date_block = soup.find(id="block-tools-date-maj")
        if date_block:
            m = re.search(r"mise à jour\s*:\s*(.+)", date_block.get_text(strip=True), re.IGNORECASE)
            if m:
                as_of = m.group(1).strip()

        quotes: dict[str, tuple[float, float]] = {}
        section = soup.find(id="slide-seance")
        if section:
            for item in section.find_all("div", class_="item"):
                spans = item.find_all("span")
                if len(spans) < 3:
                    continue
                ticker = spans[0].get_text(strip=True)
                price = self._parse_number(spans[1].get_text(strip=True))
                change_pct = self._parse_number(spans[2].get_text(strip=True))
                quotes[ticker] = (price, change_pct)

        indices: dict[str, tuple[float, float]] = {}
        market_cap = 0.0
        total_value = 0.0
        activity_table = soup.find(id="block-tools-activites-marche")
        activity_table = activity_table.find("table") if activity_table else None
        if activity_table and isinstance(activity_table, Tag):
            index_label_map = {
                "BRVM-C": "BRVM Composite",
                "BRVM-30": "BRVM 30",
                "BRVM-PRES": "BRVM Prestige",
            }
            for row in activity_table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True)
                value = self._parse_number(cells[1].get_text(strip=True))
                if label in index_label_map:
                    change_text = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    change_pct = self._parse_number(change_text)
                    indices[index_label_map[label]] = (value, change_pct)
                elif label == "Valeur des transactions":
                    total_value = value
                elif label == "Capitalisation Actions":
                    market_cap = value

        return _BrvmOrgSnapshot(
            as_of=as_of,
            quotes=quotes,
            indices=indices,
            market_cap=market_cap,
            total_value=total_value,
        )

    # ── Bulletin Officiel de la Cote PDF (lagging, once-a-day) ──────

    async def _get_latest_boc_snapshot(self) -> _BocSnapshot | None:
        """Download and parse the latest available BOC PDF, cached for an hour."""
        if self._boc_cache and (time.monotonic() - self._boc_cache[0]) < BOC_CACHE_TTL:
            return self._boc_cache[1]

        try:
            list_resp = await self._get_with_retry(BOC_LIST_URL)
            hrefs = re.findall(r'href="([^"]*boc_(\d{8})_\d+\.pdf)"', list_resp.text)
            if not hrefs:
                logger.warning("No BOC PDF links found on bulletins page")
                return self._boc_cache[1] if self._boc_cache else None
            pdf_path, _ = max(hrefs, key=lambda h: h[1])
            pdf_url = pdf_path if pdf_path.startswith("http") else f"{BRVM_BASE}{pdf_path}"

            pdf_resp = await self._get_with_retry(pdf_url)
            snapshot = self._parse_boc_pdf(pdf_resp.content)
            self._boc_cache = (time.monotonic(), snapshot)
            return snapshot
        except Exception:
            logger.warning("Failed to fetch/parse latest BOC PDF", exc_info=True)
            return self._boc_cache[1] if self._boc_cache else None

    @staticmethod
    def _parse_boc_pdf(pdf_bytes: bytes) -> _BocSnapshot:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page1_text = pdf.pages[0].extract_text() or ""

            bulletin_date = ""
            date_m = re.search(r"^\S+\s+\d{1,2}\s+\S+\s+\d{4}", page1_text, re.MULTILINE)
            if date_m:
                bulletin_date = date_m.group(0).strip()

            index_ytd: dict[str, float] = {}
            ytd_m = re.search(
                r"^Variation annuelle\s+(-?[\d,]+)\s*%\s+"
                r"Variation annuelle\s+(-?[\d,]+)\s*%\s+"
                r"Variation annuelle\s+(-?[\d,]+)\s*%",
                page1_text,
                re.MULTILINE,
            )
            if ytd_m:
                for name, pct in zip(INDEX_NAMES, ytd_m.groups()):
                    index_ytd[name] = BRVMScraper._parse_number(pct)

            principal = None
            principal_m = re.search(
                r"BRVM-PRINCIPAL\s*\(\*\*\)\s*\d+\s+([\d,]+)\s+(-?[\d,]+)\s*%\s+(-?[\d,]+)\s*%",
                page1_text,
            )
            if principal_m:
                value, change_pct, ytd_pct = (
                    BRVMScraper._parse_number(g) for g in principal_m.groups()
                )
                principal = IndexValue(
                    name="BRVM Principal",
                    value=value,
                    change_pct=change_pct,
                    ytd_change_pct=ytd_pct,
                    as_of=bulletin_date,
                )

            volumes: dict[str, int] = {}
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        if len(row) < 9:
                            continue
                        ticker = (row[1] or "").strip()
                        if ticker not in TICKER_REGISTRY:
                            continue
                        volumes[ticker] = int(BRVMScraper._parse_number(row[8] or ""))

        return _BocSnapshot(
            bulletin_date=bulletin_date,
            index_ytd=index_ytd,
            principal=principal,
            volumes=volumes,
        )

    # ── Live Quotes ──────────────────────────────────────────────

    @staticmethod
    def _build_quotes(
        snapshot: _BrvmOrgSnapshot, boc: _BocSnapshot | None
    ) -> list[StockQuote]:
        """Build StockQuote objects from homepage snapshot and optional BOC snapshot."""
        quotes: list[StockQuote] = []
        for ticker, (price, change_pct) in snapshot.quotes.items():
            registry_info = TICKER_REGISTRY.get(ticker, (ticker, "", ""))
            previous_close = price / (1 + change_pct / 100) if change_pct != -100 else price
            quotes.append(
                StockQuote(
                    ticker=ticker,
                    name=registry_info[0],
                    price=price,
                    change=round(price - previous_close, 2),
                    change_pct=change_pct,
                    volume=boc.volumes.get(ticker, 0) if boc else 0,
                    previous_close=round(previous_close, 2),
                    country=registry_info[1],
                    sector=registry_info[2],
                    as_of=snapshot.as_of or datetime.now().isoformat(timespec="minutes"),
                )
            )

        logger.info(f"Scraped {len(quotes)} quotes from brvm.org")
        return quotes

    async def get_all_quotes(self) -> list[StockQuote]:
        """All ~46 BRVM stock quotes: same-day price/change from brvm.org's
        ticker tape, volume from the latest BOC PDF (one session behind)."""
        snapshot = await self._get_brvm_org_homepage()
        boc = await self._get_latest_boc_snapshot()
        return self._build_quotes(snapshot, boc)

    async def get_quote(self, ticker: str) -> StockQuote | None:
        """Get a single stock quote by ticker."""
        ticker = ticker.upper().strip()
        quotes = await self.get_all_quotes()
        return next((q for q in quotes if q.ticker == ticker), None)

    # ── Indices ──────────────────────────────────────────────────

    @staticmethod
    def _build_indices(
        snapshot: _BrvmOrgSnapshot, boc: _BocSnapshot | None
    ) -> list[IndexValue]:
        """Build IndexValue objects from homepage snapshot and optional BOC snapshot."""
        indices: list[IndexValue] = []
        for name in INDEX_NAMES:
            value, change_pct = snapshot.indices.get(name, (0.0, 0.0))
            indices.append(
                IndexValue(
                    name=name,
                    value=value,
                    change_pct=change_pct,
                    ytd_change_pct=boc.index_ytd.get(name) if boc else None,
                    as_of=snapshot.as_of,
                )
            )

        if boc and boc.principal:
            indices.append(boc.principal)

        logger.info(f"Scraped {len(indices)} indices")
        return indices

    async def get_indices(self) -> list[IndexValue]:
        """BRVM Composite/30/Prestige same-day from brvm.org (YTD from the BOC
        PDF); BRVM Principal entirely from the BOC PDF (no homepage widget)."""
        snapshot = await self._get_brvm_org_homepage()
        boc = await self._get_latest_boc_snapshot()
        return self._build_indices(snapshot, boc)

    # ── Market Summary ───────────────────────────────────────────

    async def get_market_summary(self) -> MarketSummary:
        """Build a full market summary from scraped data with a single homepage fetch."""
        snapshot = await self._get_brvm_org_homepage()
        boc = await self._get_latest_boc_snapshot()
        quotes = self._build_quotes(snapshot, boc)
        indices = self._build_indices(snapshot, boc)

        gainers = [q for q in quotes if q.change_pct > 0]
        losers = [q for q in quotes if q.change_pct < 0]
        unchanged = [q for q in quotes if q.change_pct == 0]
        total_volume = sum(q.volume for q in quotes)

        return MarketSummary(
            date=datetime.now().strftime("%Y-%m-%d"),
            total_volume=total_volume,
            total_value=snapshot.total_value,
            market_cap=snapshot.market_cap,
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
            if (
                query_lower
                and query_lower not in name.lower()
                and query_lower not in ticker.lower()
            ):
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
