"""
Sikafinance scraper
===================
Sikafinance (sikafinance.com) is an independent West African financial
news/analysis portal. It publishes, per BRVM ticker, several fields brvm.org
and the BOC PDF simply don't have: a 1-year Beta, a 14-day RSI, a self-reported
investor sentiment poll (buy/sell/hold vote counts), a dated news headline
feed, and a dividend-yield history table already computed.

Coverage note: not every BRVM ticker gets a Sikafinance page/news feed —
in practice it's strongest on the more liquid, more-covered names. Treat a
404/empty result as "no coverage for this ticker," not as a scraper bug.

Premium articles: Sikafinance paywalls its deeper "analysis" pieces (path
prefix `/premium/`) — only the headline and a one-line teaser are public.
This scraper only ever reads the free headline; it never attempts to log
in or pay for content. The headline itself is still useful as a search
query to find independent coverage of the same story elsewhere.

All data here is unofficial and dated per Sikafinance's own "Cotations en
direct, différé 15 min" disclaimer (~15-minute delayed quotes) — for the
authoritative end-of-day print, use brvm.org / the BOC PDF (this project's
main `BRVMScraper`), not this module.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from brvm_mcp.models import (
    SikaDividendEntry,
    SikaHistoricalRange,
    SikaNewsItem,
    SikaSentiment,
    SikaStockPage,
)

logger = logging.getLogger(__name__)

SIKA_BASE = "https://www.sikafinance.com"

# Sikafinance URLs suffix the ticker with the listing country's ISO-2 code,
# e.g. cotation_CBIBF.bf, cotation_BICB.bj, cotation_SLBC.ci — not the
# ticker alone. Built from this project's own TICKER_REGISTRY country names.
_COUNTRY_TO_ISO2: dict[str, str] = {
    "Côte d'Ivoire": "ci",
    "Bénin": "bj",
    "Burkina Faso": "bf",
    "Mali": "ml",
    "Niger": "ne",
    "Sénégal": "sn",
    "Togo": "tg",
    "Guinée-Bissau": "gw",
}


class SikaFinanceScraper:
    """Async scraper for sikafinance.com ticker pages and news feeds."""

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

    async def close(self):
        await self._client.aclose()

    async def _get(self, url: str) -> httpx.Response | None:
        """GET with retry on 429/5xx/transport errors. Returns None on 404
        (ticker not covered by Sikafinance) instead of raising."""
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self._client.get(url)
            except httpx.TransportError:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF[attempt])
                    continue
                raise
            if resp.status_code == 404:
                return None
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF[attempt])
                    continue
            resp.raise_for_status()
            return resp
        return None

    @staticmethod
    def _parse_number(text: str) -> float:
        """Same French/English number parsing convention as BRVMScraper."""
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

    @staticmethod
    def _ticker_slug(ticker: str, country: str) -> str:
        """e.g. ('CBIBF', 'Burkina Faso') -> 'CBIBF.bf'."""
        iso2 = _COUNTRY_TO_ISO2.get(country, "")
        if not iso2:
            raise ValueError(f"No Sikafinance country suffix known for '{country}'")
        return f"{ticker}.{iso2}"

    def _parse_news_block(self, container: Tag, base_url: str) -> list[SikaNewsItem]:
        """A Sikafinance news block is a flat sequence of
        <span class="sp1">date</span><a class="lks"?>title</a><br/> siblings —
        not one <li> per item, so we walk siblings and pair each span with
        the anchor that immediately follows it."""
        items: list[SikaNewsItem] = []
        spans = container.find_all("span", class_="sp1")
        for span in spans:
            anchor = span.find_next_sibling("a")
            if not anchor or not anchor.get("href"):
                continue
            href = anchor["href"]
            items.append(
                SikaNewsItem(
                    date=span.get_text(strip=True),
                    title=anchor.get_text(strip=True),
                    url=urljoin(base_url, href),
                    is_premium=href.startswith("/premium/"),
                )
            )
        return items

    async def get_stock_page(self, ticker: str, country: str) -> SikaStockPage | None:
        """Fetch and parse a ticker's main Sikafinance page: quote, beta, RSI,
        capital exchanged, market cap, historical ranges, dividends, recent
        news, and investor sentiment.

        Returns None if Sikafinance has no page for this ticker.
        """
        slug = self._ticker_slug(ticker, country)
        url = f"{SIKA_BASE}/marches/cotation_{slug}"
        resp = await self._get(url)
        if resp is None:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        name_el = soup.select_one(".quotebarE h1")
        name = name_el.get_text(strip=True) if name_el else ticker

        isin_el = soup.select_one(".quotebarE .innerUpu")
        isin = ""
        if isin_el:
            m = re.search(r"([A-Z]{2}\d{10})", isin_el.get_text())
            if m:
                isin = m.group(1)

        cot1 = soup.select_one("#cot1c")
        price = change_pct = 0.0
        field_map: dict[str, float] = {}
        if cot1:
            price_el = cot1.select_one(".cot1u")
            if price_el:
                # price is the element's own direct text; the % change lives in
                # a nested <div class="fr"> sibling. Some tickers suffix "XOF"
                # here, others don't (e.g. CIEC) -- reading only the direct
                # text (not get_text(), which pulls in descendant text too)
                # avoids concatenating the price with the nested change_pct.
                own_text = "".join(t for t in price_el.find_all(string=True, recursive=False))
                price = self._parse_number(own_text.replace("XOF", ""))
            change_el = cot1.select_one(".quote_up, .quote_down")
            if change_el:
                change_pct = self._parse_number(change_el.get_text(strip=True))
            for table in cot1.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) == 2:
                        label = cells[0].get_text(strip=True)
                        field_map[label] = self._parse_number(cells[1].get_text(strip=True))

        historical_ranges: list[SikaHistoricalRange] = []
        for table in soup.select("table.tableVar"):
            header_cells = [th.get_text(strip=True) for th in table.select("thead th")]
            if "Plus Haut" not in header_cells:
                continue
            for row in table.select("tbody tr"):
                cells = row.find_all("td")
                if len(cells) != 4:
                    continue
                # young listings show "-" for windows (3/5 years) they haven't
                # existed for yet -- keep that as None, not a misleading 0.0
                is_placeholder = cells[1].get_text(strip=True) == "-"
                high, low, chg = (
                    (None, None, None)
                    if is_placeholder
                    else (
                        self._parse_number(cells[1].get_text(strip=True)),
                        self._parse_number(cells[2].get_text(strip=True)),
                        self._parse_number(cells[3].get_text(strip=True)),
                    )
                )
                period = cells[0].get_text(strip=True)
                entry = SikaHistoricalRange(period=period, high=high, low=low, change_pct=chg)
                historical_ranges.append(entry)
            break  # only one such table per page

        dividends: list[SikaDividendEntry] = []
        div_header = soup.find(string=re.compile("DERNIERS DIVIDENDES"))
        if div_header:
            div_table = div_header.find_parent().find_next("table", class_="tableVar")
            if div_table:
                for row in div_table.select("tbody tr"):
                    cells = row.find_all("td")
                    if len(cells) != 3:
                        continue
                    yield_text = cells[2].get_text(strip=True)
                    has_yield = yield_text and yield_text != "-"
                    dividends.append(
                        SikaDividendEntry(
                            year=cells[0].get_text(strip=True),
                            amount=self._parse_number(cells[1].get_text(strip=True)),
                            yield_pct=self._parse_number(yield_text) if has_yield else None,
                        )
                    )

        recent_news: list[SikaNewsItem] = []
        news_header = soup.find(string=re.compile("ACTUALITES"))
        if news_header:
            news_block = news_header.find_parent().find_next_sibling("div", class_="home_content")
            if news_block:
                recent_news = self._parse_news_block(news_block, SIKA_BASE)

        sentiment = None
        consensus_input = soup.select_one("#consensusData")
        if consensus_input and consensus_input.get("value"):
            parts = consensus_input["value"].split(";")
            if len(parts) == 3 and all(p.strip().lstrip("-").isdigit() for p in parts):
                buy, sell, hold = (int(p) for p in parts)
                sentiment = SikaSentiment(buy_votes=buy, sell_votes=sell, hold_votes=hold)

        return SikaStockPage(
            ticker=ticker,
            name=name,
            isin=isin,
            country=country,
            price=price,
            change_pct=change_pct,
            volume=int(field_map.get("Volume (titres)", 0)),
            value_traded=field_map.get("Volume (XOF )", 0.0),
            open=field_map.get("Ouverture", 0.0),
            high=field_map.get("Plus haut", 0.0),
            low=field_map.get("Plus bas", 0.0),
            previous_close=field_map.get("Clôture veille", 0.0),
            beta_1y=field_map.get("Beta 1 an"),
            rsi=field_map.get("RSI"),
            capital_exchanged_pct=field_map.get("Capital échangé"),
            market_cap=field_map.get("Valorisation"),
            historical_ranges=historical_ranges,
            dividends=dividends,
            recent_news=recent_news,
            sentiment=sentiment,
            source_url=url,
        )

    async def get_news(self, ticker: str, country: str, limit: int = 30) -> list[SikaNewsItem]:
        """Fetch a ticker's full dated news feed (more complete and with
        timestamps, vs. the ~8 most recent headlines shown on the main page).

        Headline titles are meant to be used as search queries against a
        general web search tool to find full coverage of paywalled stories —
        this method never fetches or pays for premium article bodies.
        """
        slug = self._ticker_slug(ticker, country)
        url = f"{SIKA_BASE}/marches/news_valeur?s={slug}"
        resp = await self._get(url)
        if resp is None:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        container = soup.select_one("div.home_content")
        if not container:
            return []
        return self._parse_news_block(container, SIKA_BASE)[:limit]
