# CLAUDE.md — BRVM MCP Server

## What this project is

The **first MCP server for the BRVM** (Bourse Régionale des Valeurs Mobilières), the regional stock exchange of 8 West African UEMOA countries. It exposes live market data (quotes, indices, top movers, company info) to any MCP-compatible AI agent via the Model Context Protocol.

This is a **portfolio piece** for an Anthropic Forward Deployed Engineer application — code quality, documentation, and MCP best practices matter as much as functionality.

## Tech stack

- **Python 3.11+** with **uv** as package manager
- **FastMCP** (mcp SDK ≥1.27.0) — decorator-based MCP framework
- **httpx** — async HTTP client for scraping
- **BeautifulSoup4 + lxml** — HTML parsing
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

- **afx.kwayisi.org/brvm/** — HTML page with live BRVM quotes, indices, trading summaries
- No official BRVM API exists; we scrape responsibly (polite User-Agent, 5min cache TTL)
- The HTML structure of afx may change — the scraper needs to be resilient and tested against the real page
- The `TICKER_REGISTRY` in `scrapers/__init__.py` is a static enrichment layer (company names, countries, sectors)

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

- The afx.kwayisi.org HTML structure is the source of truth — always `curl https://afx.kwayisi.org/brvm/` and inspect the actual HTML before adjusting selectors
- Number parsing must handle French formatting: `1 234,56` (space thousands separator, comma decimal)
- Non-breaking spaces (`\xa0`) are common in French financial data
- The scraper should never crash on unexpected HTML — return empty results and log warnings
- Test with real network calls, then add VCR cassettes for offline CI

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