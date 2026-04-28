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
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from brvm_mcp.cache import BRVMCache
from brvm_mcp.scrapers import BRVMScraper

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,  # MCP uses stdout for protocol; logs go to stderr
)
logger = logging.getLogger("brvm-mcp")

# ── Lifespan (startup / shutdown) ────────────────────────────────

scraper: BRVMScraper | None = None
cache: BRVMCache | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize scraper and cache on startup, clean up on shutdown."""
    global scraper, cache
    scraper = BRVMScraper()
    cache = BRVMCache()
    logger.info("BRVM MCP Server started — scraper and cache initialized")
    try:
        yield
    finally:
        if scraper:
            await scraper.close()
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
