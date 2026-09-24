"""
BRVM MCP Server
===============
The first MCP server for West Africa's regional stock exchange.

Exposes BRVM market data (quotes, indices, company info, top movers)
to any MCP-compatible AI agent — Claude Desktop, ChatGPT, Cursor,
VS Code Copilot, LangGraph agents, and more.

Usage:
    # stdio transport (Claude Desktop, Cursor)
    brvm-mcp

    # Streamable HTTP (remote agents, web apps)
    brvm-mcp --transport http --port 8000

Author: Dilane Fogué Kamga
License: MIT
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from brvm_mcp.cache import BRVMCache
from brvm_mcp.scrapers import TICKER_REGISTRY, BRVMScraper
from brvm_mcp.scrapers.sikafinance import SikaFinanceScraper

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,  # MCP uses stdout for protocol; logs go to stderr
)
logger = logging.getLogger("brvm-mcp")

# ── Lifespan (startup / shutdown) ────────────────────────────────

scraper: BRVMScraper | None = None
sika_scraper: SikaFinanceScraper | None = None
cache: BRVMCache | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize scraper and cache on startup, clean up on shutdown."""
    global scraper, sika_scraper, cache
    scraper = BRVMScraper()
    sika_scraper = SikaFinanceScraper()
    cache = BRVMCache()
    logger.info("BRVM MCP Server started — scraper and cache initialized")
    try:
        yield
    finally:
        if scraper:
            await scraper.close()
        if sika_scraper:
            await sika_scraper.close()
        if cache:
            cache.close()
        logger.info("BRVM MCP Server shut down")


# ── MCP Server ───────────────────────────────────────────────────

mcp = FastMCP(
    "BRVM Market Data",
    instructions=(
        "Live market data from the BRVM (Bourse Régionale des Valeurs Mobilières), "
        "the regional stock exchange of 8 West African UEMOA member states. "
        "Provides stock quotes, index values, top movers, company info, and market summaries."
    ),
    lifespan=lifespan,
)


# ── Tools ────────────────────────────────────────────────────────


@mcp.tool()
async def get_market_summary() -> str:
    """
    Get today's BRVM market summary including total volume, value traded,
    number of gainers/losers, and all index values.

    Returns a JSON object with the full trading session overview.
    """
    assert scraper and cache

    cached = cache.get("market_summary")
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    summary = await scraper.get_market_summary()
    data = summary.model_dump()
    cache.set("market_summary", data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_stock_price(ticker: str) -> str:
    """
    Get the current price and trading data for a specific BRVM-listed stock.

    Args:
        ticker: The BRVM ticker symbol (e.g., SNTS for Sonatel, SGBC for Société Générale CI,
                ETIT for Ecobank Transnational, ORAC for Orange CI, ONTBF for Onatel).

    Returns a JSON object with price, change, volume, and company details.
    """
    assert scraper and cache
    ticker = ticker.upper().strip()

    cached = cache.get(f"quote:{ticker}")
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    quote = await scraper.get_quote(ticker)
    if not quote:
        return json.dumps(
            {"error": f"Ticker '{ticker}' not found on BRVM. Use search_stocks to find valid tickers."}
        )

    data = quote.model_dump()
    cache.set(f"quote:{ticker}", data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_indices() -> str:
    """
    Get current values for all BRVM indices: BRVM Composite (BRVM-CI),
    BRVM 30, BRVM Prestige, BRVM Principal, and sector indices.

    Returns a JSON array of index objects with value, change, and YTD performance.
    """
    assert scraper and cache

    cached = cache.get("indices")
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    indices = await scraper.get_indices()
    data = [idx.model_dump() for idx in indices]
    cache.set("indices", data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_top_movers(n: int = 5) -> str:
    """
    Get today's top gaining and losing stocks on the BRVM.

    Args:
        n: Number of stocks to return per category (default 5, max 10).

    Returns a JSON object with 'gainers' and 'losers' arrays.
    """
    assert scraper and cache
    n = min(max(n, 1), 10)

    cached = cache.get(f"top_movers:{n}")
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    movers = await scraper.get_top_movers(n=n)
    data = {
        "gainers": [m.model_dump() for m in movers["gainers"]],
        "losers": [m.model_dump() for m in movers["losers"]],
    }
    cache.set(f"top_movers:{n}", data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_company_info(ticker: str) -> str:
    """
    Get detailed information about a BRVM-listed company.

    Args:
        ticker: The BRVM ticker symbol.

    Returns company name, country, sector, and market cap.
    """
    assert scraper

    info = await scraper.get_company_info(ticker)
    if not info:
        return json.dumps(
            {"error": f"Company '{ticker}' not found. Use search_stocks to browse available companies."}
        )
    return json.dumps(info.model_dump(), ensure_ascii=False, indent=2)


@mcp.tool()
async def search_stocks(
    query: str = "",
    country: str = "",
    sector: str = "",
) -> str:
    """
    Search BRVM-listed stocks by name, country, or sector.

    Args:
        query: Free-text search on company name or ticker (e.g., 'orange', 'ecobank', 'SNTS').
        country: Filter by UEMOA country (e.g., 'Sénégal', 'Côte d\\'Ivoire', 'Burkina Faso',
                 'Bénin', 'Togo', 'Mali', 'Niger', 'Guinée-Bissau').
        sector: Filter by sector (e.g., 'Services Financiers', 'Agriculture',
                'Services Publics', 'Industrie', 'Distribution', 'Transport').

    Returns a JSON array of matching companies.
    At least one filter must be provided.
    """
    assert scraper

    if not query and not country and not sector:
        return json.dumps(
            {"error": "Provide at least one filter: query, country, or sector."}
        )

    results = await scraper.search_stocks(query=query, country=country, sector=sector)
    return json.dumps(
        [r.model_dump() for r in results],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def list_tickers() -> str:
    """
    List all BRVM ticker symbols with their company names, countries, and sectors.

    Useful for discovering available tickers before calling get_stock_price.
    Returns a JSON array of all ~46 listed companies.
    """
    from brvm_mcp.scrapers import TICKER_REGISTRY

    tickers = [
        {
            "ticker": t,
            "name": info[0],
            "country": info[1],
            "sector": info[2],
        }
        for t, info in sorted(TICKER_REGISTRY.items())
    ]
    return json.dumps(tickers, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_sika_stock_page(ticker: str) -> str:
    """
    Get a BRVM stock's Sikafinance page: fields brvm.org/the BOC don't have —
    1-year Beta, 14-day RSI, % of share capital traded today, market cap,
    high/low/change over 1 week / 1 month / YTD / 1-3-5 years, dividend
    history with computed yields, the ~8 most recent news headlines, and a
    self-reported investor sentiment poll (buy/sell/hold vote counts).

    Prices are ~15-minute delayed (Sikafinance's own disclaimer) — for the
    authoritative end-of-day print use get_stock_price instead.

    Args:
        ticker: The BRVM ticker symbol (e.g., CBIBF, BICB, SLBC).

    Returns a JSON object, or an error if this ticker has no Sikafinance page.
    """
    assert sika_scraper and cache
    ticker = ticker.upper().strip()

    info = TICKER_REGISTRY.get(ticker)
    if not info:
        return json.dumps(
            {"error": f"Ticker '{ticker}' not in the BRVM registry. Use search_stocks."}
        )
    country = info[1]

    cache_key = f"sika_page:{ticker}"
    cached = cache.get(cache_key)
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    try:
        page = await sika_scraper.get_stock_page(ticker, country)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not page:
        return json.dumps(
            {"error": f"Sikafinance has no page for '{ticker}' (uncovered, or lookup failed)."}
        )

    data = page.model_dump()
    cache.set(cache_key, data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_sika_news(ticker: str, n: int = 15) -> str:
    """
    Get a BRVM stock's full dated news headline feed from Sikafinance
    (more complete, with timestamps, than the short list in
    get_sika_stock_page — useful for scanning a ticker's news history or
    spotting the date of a specific event).

    Some headlines link to paywalled "Sika Premium" analysis pieces
    (is_premium: true) — this tool never fetches or pays for that content,
    only the free headline. Use a headline as a search query with a general
    web search tool to find independent coverage of the same story.

    Args:
        ticker: The BRVM ticker symbol (e.g., CBIBF, BICB, SLBC).
        n: Max number of headlines to return (default 15, max 50).

    Returns a JSON array of {date, title, url, is_premium} objects.
    """
    assert sika_scraper and cache
    ticker = ticker.upper().strip()
    n = min(max(n, 1), 50)

    info = TICKER_REGISTRY.get(ticker)
    if not info:
        return json.dumps(
            {"error": f"Ticker '{ticker}' not in the BRVM registry. Use search_stocks."}
        )
    country = info[1]

    cache_key = f"sika_news:{ticker}:{n}"
    cached = cache.get(cache_key)
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    try:
        news = await sika_scraper.get_news(ticker, country, limit=n)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    data = [item.model_dump() for item in news]
    cache.set(cache_key, data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_brvm_filings(n: int = 30) -> str:
    """
    Get the market-wide BRVM regulatory filings feed from Sikafinance
    (communiqués BRVM): every issuer's recent official documents — activity
    reports, financial statements, dividend notices, listing suspensions,
    financial ratings, AGM notices, etc. — each with a direct PDF link.

    Not scoped to one ticker; covers the whole exchange. Use
    search_brvm_filings instead if you're looking for a specific
    company or document type.

    Args:
        n: Max number of filings to return, most recent first (default 30, max 50).

    Returns a JSON array of {date, issuer, title, pdf_url} objects.
    """
    assert sika_scraper and cache
    n = min(max(n, 1), 50)

    cache_key = f"sika_filings:{n}"
    cached = cache.get(cache_key)
    if cached:
        return json.dumps(cached, ensure_ascii=False, indent=2)

    filings = await sika_scraper.get_filings(limit=n)
    data = [f.model_dump() for f in filings]
    cache.set(cache_key, data)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def search_brvm_filings(query: str, n: int = 50) -> str:
    """
    Search the market-wide BRVM filings feed (see get_brvm_filings) by a
    free-text match against the issuer name or document title — e.g.
    'dividende', 'suspension', 'ECOBANK', 'rapport d'activités'.

    This searches titles/issuer names only, not the PDF contents — it
    won't find a filing whose title doesn't mention your query even if
    the document body does.

    Args:
        query: Case-insensitive substring to match (required).
        n: Max number of feed rows to scan before searching (default 50, the
           feed's practical size — raise only if you know it has grown).

    Returns a JSON array of matching {date, issuer, title, pdf_url} objects.
    """
    assert sika_scraper
    if not query.strip():
        return json.dumps({"error": "query must not be empty."})

    n = min(max(n, 1), 200)
    filings = await sika_scraper.get_filings(limit=n)
    needle = query.strip().lower()
    matches = [f for f in filings if needle in f.issuer.lower() or needle in f.title.lower()]
    return json.dumps([f.model_dump() for f in matches], ensure_ascii=False, indent=2)


@mcp.tool()
async def download_brvm_filing(pdf_url: str) -> str:
    """
    Download a filing PDF found via get_brvm_filings or search_brvm_filings
    to local disk, so it can be read (e.g. with a PDF-reading tool).

    Only accepts URLs on sikafinance.com — pass a pdf_url exactly as
    returned by those two tools, not an arbitrary link.

    Args:
        pdf_url: The filing's pdf_url field from get_brvm_filings/search_brvm_filings.

    Returns a JSON object with the local file path and size in bytes.
    """
    assert sika_scraper
    dest_dir = Path.home() / ".cache" / "brvm-mcp" / "filings"
    try:
        local_path = await sika_scraper.download_filing(pdf_url, str(dest_dir))
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    size = Path(local_path).stat().st_size
    return json.dumps({"path": local_path, "size_bytes": size}, ensure_ascii=False, indent=2)


# ── Resources ────────────────────────────────────────────────────


@mcp.resource("brvm://about")
async def about_brvm() -> str:
    """Overview of the BRVM exchange for context injection."""
    return (
        "The BRVM (Bourse Régionale des Valeurs Mobilières) is the regional stock exchange "
        "of the 8 UEMOA member states: Bénin, Burkina Faso, Côte d'Ivoire, Guinée-Bissau, "
        "Mali, Niger, Sénégal, and Togo. Headquartered in Abidjan, it lists ~46 companies "
        "with a total market capitalization of ~15.5 trillion XOF (~$27.8 billion USD). "
        "Trading is fully electronic. Prices are quoted in CFA Francs (XOF). "
        "Key indices: BRVM Composite (BRVM-CI), BRVM 30, BRVM Prestige, BRVM Principal. "
        "Sector indices: BRVM Agriculture, BRVM Services Financiers, BRVM Industrie, etc. "
        "Settlement cycle: T+2 (adopted December 2025). "
        "Upcoming: derivatives market launch December 18, 2026 (futures on indices/stocks), "
        "ETF listings, and a linked agricultural commodities exchange (BMPA CI)."
    )


# ── Prompts ──────────────────────────────────────────────────────


@mcp.prompt()
def analyze_stock(ticker: str) -> str:
    """Generate a prompt for analyzing a BRVM stock."""
    return (
        f"Analyze the BRVM-listed stock {ticker}. "
        f"First, call get_stock_price('{ticker}') to get the current price. "
        f"Then call get_company_info('{ticker}') for company details. "
        f"Compare with the overall market using get_market_summary(). "
        f"Provide: current valuation assessment, sector positioning within UEMOA, "
        f"and how this stock fits within the BRVM's upcoming derivatives launch."
    )


@mcp.prompt()
def market_report() -> str:
    """Generate a prompt for a full BRVM market report."""
    return (
        "Create a comprehensive BRVM daily market report. "
        "1. Call get_market_summary() for the session overview. "
        "2. Call get_top_movers(5) for the biggest movers. "
        "3. Call get_indices() for all index values. "
        "Structure the report with: Executive Summary, Index Performance, "
        "Top Gainers & Losers, Volume Analysis, and Outlook. "
        "Include context about the BRVM's position as a regional exchange "
        "serving 8 UEMOA countries."
    )


# ── Entry Point ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="BRVM MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio for Claude Desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP transport (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
