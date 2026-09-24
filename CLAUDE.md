# CLAUDE.md — BRVM MCP Server

## What this project is

The **first MCP server for the BRVM** (Bourse Régionale des Valeurs Mobilières), the regional stock exchange of 8 West African UEMOA countries. It exposes live market data (quotes, indices, top movers, company info) to any MCP-compatible AI agent via the Model Context Protocol.

This is a **portfolio piece** for an Anthropic Forward Deployed Engineer application — code quality, documentation, and MCP best practices matter as much as functionality.

## Tech stack

- **Python 3.11+** with **uv** as package manager
- **FastMCP** (mcp SDK ≥1.27.0) — decorator-based MCP framework
- **httpx** — async HTTP client for scraping
- **BeautifulSoup4 + lxml** — HTML parsing
- **pdfplumber** — BOC PDF parsing (text regex + table extraction)
- **Pydantic v2** — data models
- **diskcache** — TTL-based caching (5min default)
- **pytest + pytest-asyncio** — testing

## Project structure

```
src/brvm_mcp/
├── __init__.py              # Package version
├── server.py                # MCP server entry point (tools, resources, prompts)
├── cache.py                 # Disk cache layer
├── scrapers/__init__.py     # BRVMScraper class — async web scraper
└── models/__init__.py       # Pydantic models (StockQuote, IndexValue, MarketSummary, etc.)
tests/
└── test_brvm.py             # Unit + integration tests
```

## Key commands

```bash
uv sync                                    # Install dependencies
uv run brvm-mcp                            # Run server (stdio transport, for Claude Desktop)
uv run brvm-mcp --transport streamable-http --port 8000  # Run server (HTTP transport)
uv run pytest                              # Run tests
uv run pytest -x -v                        # Run tests, stop on first failure
npx @modelcontextprotocol/inspector uv run brvm-mcp      # Test with MCP Inspector
uv run ruff check src/                     # Lint
uv run mypy src/                           # Type check
```

## Primary data source

Everything is sourced from **brvm.org** (the exchange's own site), across two pages:

- **Homepage** (`https://www.brvm.org/`) — same-day ticker tape (`#slide-seance`) and
  "Activités du marché" widget (`#block-tools-activites-marche`): price, change %,
  market cap, transaction value, and BRVM Composite/30/Prestige value+change %.
- **Bulletin Officiel de la Cote (BOC) PDF** (`/fr/bulletins-officiels-de-la-cote`,
  linked as `boc_YYYYMMDD_2.pdf`) — per-stock volume, index YTD %, and the BRVM
  Principal index. Parsed with `pdfplumber` (text regex for the index summary,
  `extract_tables()` for the per-stock table), cached 1h since it only updates once
  a day. This PDF lags one trading session — that's the nature of the bulletin, not
  a bug, so those 3 fields are always one session behind the homepage-sourced ones.

No official BRVM API exists; we scrape responsibly (polite User-Agent, 5min tool-level
cache TTL, 1h BOC cache). The HTML/PDF structure may change — the scraper needs to be
resilient and tested against the real page/PDF, not just fixtures.

The `TICKER_REGISTRY` in `scrapers/__init__.py` is a static enrichment layer (company
names, countries, sectors) — the exchange's pages don't carry full company names.

**History**: this used to scrape `afx.kwayisi.org/brvm/` as primary, with brvm.org as
an unused "fallback" in name only. kwayisi turned out to lag a full trading session on
everything *and* have real uptime problems, so it was dropped entirely — see the
`scrapers/__init__.py` module docstring for the full story before reintroducing any
third-party mirror as a source.

## Secondary data source (per-ticker enrichment)

`scrapers/sikafinance.py` adds fields brvm.org and the BOC simply don't have:
1-year Beta, 14-day RSI, % of share capital traded, a self-reported investor
sentiment poll (buy/sell/hold votes), and a dated news headline feed — see
`get_sika_stock_page`/`get_sika_news`.

Not every ticker is covered (Sikafinance is strongest on the more liquid
names) — a 404/empty result means "no coverage," not a scraper bug. Some
headlines link to paywalled "Sika Premium" analysis (`is_premium: true`);
the scraper only ever reads the free headline, never logs in or pays —
the headline itself is meant to be used as a web-search query for
independent coverage of the same story.

## MCP design decisions

- **7 tools**, under Anthropic's recommended limit of 20 per server
- Tools return **JSON strings** (not raw dicts) because FastMCP serializes tool outputs as text
- **Lifespan pattern** for scraper/cache initialization and cleanup
- **Cache layer** sits between tools and scraper to avoid re-scraping on rapid tool calls
- **Resources** provide static context (exchange overview) for RAG-style injection
- **Prompts** are reusable templates that orchestrate multiple tool calls

## Code style

- Type hints everywhere (Python 3.11+ syntax: `X | None` not `Optional[X]`)
- Async/await for all I/O
- Pydantic models for all data structures — no raw dicts crossing boundaries
- Ruff for linting, line length 100
- French and English comments are both fine (bilingual project)
- Docstrings on all public functions — these become MCP tool descriptions visible to agents

## When editing the scraper

- The real brvm.org homepage HTML and the latest BOC PDF are the source of truth —
  `curl https://www.brvm.org/` and download the latest `boc_*.pdf` from
  `/fr/bulletins-officiels-de-la-cote` before adjusting selectors or regexes
- Number parsing must handle French formatting: `1 234,56` (space thousands separator, comma decimal)
- Non-breaking spaces (`\xa0`) are common in French financial data
- The scraper should never crash on unexpected HTML/PDF — return empty results and log warnings
- Test with real network calls, then add VCR cassettes for offline CI
- The BOC PDF's per-stock table is parsed via `pdfplumber.extract_tables()`, not raw
  text — the sector-code column wraps to its own line in plain text extraction, which
  breaks naive regex parsing; structured table extraction handles it correctly

## When adding new tools

1. Add the Pydantic model in `models/__init__.py`
2. Add the scraper method in `scrapers/__init__.py`
3. Add the tool in `server.py` with `@mcp.tool()` decorator
4. Tool docstring = what the AI agent sees — be precise about parameters and return format
5. Add cache integration (check cache → scrape → store in cache)
6. Add tests in `tests/test_brvm.py`
7. Update README.md tool table

## Roadmap context

The BRVM is launching:
- **Derivatives** (futures on indices/stocks) on December 18, 2026
- **ETFs** in 2026–2027
- **BMPA CI** agricultural commodities exchange (cashew, maize, cola nut)

The server should evolve to cover these as data becomes available. Planned versions:
- v0.2: Historical OHLCV data
- v0.3: Corporate announcements feed
- v0.4: BMPA CI commodities
- v0.5: Derivatives data
- v1.0: OAuth + rate limiting + MCP Registry publication

## Don't

- Don't bypass authentication or rate limits on any source
- Don't store credentials in code — use env vars
- Don't return tool errors as exceptions — return JSON error objects so the agent can handle them gracefully
- Don't use `Optional[X]` — use `X | None` (Python 3.11+)
- Don't add tools beyond what we can actually scrape — no hallucinated data