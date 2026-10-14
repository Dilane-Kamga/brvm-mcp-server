# 🇨🇮 BRVM MCP Server

**The first MCP server for West Africa's regional stock exchange.**

Connect any AI agent — Claude, ChatGPT, Cursor, Copilot, LangGraph — to live market data from the [BRVM](https://www.brvm.org/) (Bourse Régionale des Valeurs Mobilières), serving 8 UEMOA member states across West Africa.

![MCP](https://img.shields.io/badge/MCP-1.27+-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
[![CI](https://github.com/Dilane-Kamga/brvm-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Dilane-Kamga/brvm-mcp-server/actions/workflows/ci.yml)

---

## Why?

The BRVM lists ~46 companies across Bénin, Burkina Faso, Côte d'Ivoire, Guinée-Bissau, Mali, Niger, Sénégal, and Togo, with a combined market cap of about 21 trillion XOF (brvm.org, 2026-10-14). Yet it has **no public API**. This server bridges that gap, making BRVM data accessible to the AI ecosystem via the [Model Context Protocol](https://modelcontextprotocol.io).

### What's coming on the BRVM
- **December 18, 2026**: First derivatives market in francophone West Africa (futures on indices and stocks)
- **2026–2027**: ETF listings
- **2026**: Agricultural commodities exchange (BMPA CI) — cashew, maize, cola nut

This server is built to grow alongside these developments.

## Features

### Tools (9)
| Tool | Description |
|------|-------------|
| `get_market_summary` | Full trading session overview: volume, value, gainers/losers, indices |
| `get_stock_price` | Current quote for a specific ticker (price, change, volume) |
| `get_indices` | All BRVM indices: Composite, BRVM 30, Prestige, Principal, sectors |
| `get_top_movers` | Top N gainers and losers of the day |
| `get_company_info` | Company details: name, country, sector, market cap |
| `search_stocks` | Search by name, country, or sector |
| `list_tickers` | All ~46 BRVM tickers with metadata |
| `get_sika_stock_page` | Sikafinance page of a ticker: beta, RSI, % of capital traded, dividend history, price ranges, recent headlines, investor poll |
| `get_sika_news` | Dated news headlines of a ticker, from Sikafinance |

### Resources
| URI | Description |
|-----|-------------|
| `brvm://about` | BRVM exchange overview for context injection |

### Prompts
| Prompt | Description |
|--------|-------------|
| `analyze_stock` | Structured analysis of a BRVM stock |
| `market_report` | Full daily market report template |

## Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install & Run

```bash
# Clone
git clone https://github.com/Dilane-Kamga/brvm-mcp-server.git
cd brvm-mcp-server

# Install
uv sync

# Run (stdio — for Claude Desktop / Cursor)
uv run brvm-mcp

# Run (HTTP — for remote agents / web apps)
uv run brvm-mcp --transport streamable-http --port 8000
```

### Connect to Claude Desktop

Add to your Claude Desktop config: `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows.

```json
{
  "mcpServers": {
    "brvm": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/brvm-mcp-server", "brvm-mcp"]
    }
  }
}
```

Quit Claude Desktop completely and start it again: it reads the config only at startup. The BRVM tools then appear in the tools menu of a conversation.

### Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run brvm-mcp
```

### Docker (remote deployment)

```bash
docker build -t brvm-mcp .
docker run -p 8000:8000 brvm-mcp
```

## Example Conversations

Once connected, you can ask Claude:

> *"What's the BRVM market doing today?"*
> → Calls `get_market_summary()`, returns full session data

> *"Show me Sonatel's stock price"*
> → Calls `get_stock_price("SNTS")`

> *"What does Sikafinance show for Sonatel: RSI, beta, latest news?"*
> → Calls `get_sika_stock_page("SNTS")`

> *"Which BRVM stocks are from Sénégal?"*
> → Calls `search_stocks(country="Sénégal")`

> *"Give me a full market report"*
> → Uses the `market_report` prompt to orchestrate multiple tool calls

> *"Which stocks dropped the most today?"*
> → Calls `get_top_movers()`, focuses on losers

## Architecture

```
┌──────────────────┐     MCP (stdio/HTTP)     ┌──────────────────┐
│   AI Agent       │◄────────────────────────►│  BRVM MCP Server │
│ (Claude, GPT,    │                          │                  │
│  Cursor, etc.)   │                          │  FastMCP + Tools │
└──────────────────┘                          │  + Cache Layer   │
                                              └────────┬─────────┘
                                                       │ httpx
                              ┌────────────────────────┴───────────────┐
                     ┌────────▼─────────┐                    ┌─────────▼────────┐
                     │   brvm.org       │                    │  sikafinance.com │
                     │ • Homepage (same-│                    │ • Ticker pages   │
                     │   day price/idx) │                    │   (beta, RSI,    │
                     │ • BOC PDF (volume│                    │   dividends)     │
                     │   /YTD/Principal,│                    │ • News headlines │
                     │   1h cache)      │                    │   (15 min delay) │
                     └──────────────────┘                    └──────────────────┘
```

- **FastMCP**: Decorator-based MCP framework (official Python SDK)
- **httpx**: Async HTTP client for scraping
- **BeautifulSoup4 + lxml**: HTML parsing
- **pdfplumber**: BOC PDF parsing (index summary regex + per-stock table extraction)
- **diskcache**: TTL-based disk caching (5min default, respectful of sources)
- **Pydantic**: Structured data models

Prices, indices and volumes come from the exchange's own site (`brvm.org`). Sikafinance adds
fields the exchange does not publish. An earlier version scraped `afx.kwayisi.org` as its primary
source; it lagged a full trading session and had uptime problems, so it was dropped.

## Roadmap

- [ ] **v0.2** — Historical price data (OHLCV bars)
- [ ] **v0.3** — BRVM official announcements / corporate actions feed
- [ ] **v0.4** — BMPA CI commodities data (when available)
- [ ] **v0.5** — Derivatives data (futures, options — post Dec 2026 launch)
- [ ] **v1.0** — OAuth + rate limiting for multi-user deployment
- [ ] Register on [MCP Registry](https://registry.modelcontextprotocol.io)

## Data sources and terms

| Source | What it provides | Freshness |
|--------|------------------|-----------|
| [brvm.org](https://www.brvm.org/) homepage | Prices, % change, market cap, value traded, BRVM Composite / 30 / Prestige | Same day |
| Bulletin Officiel de la Cote (PDF on brvm.org) | Volume per stock, year-to-date % of the indices, BRVM Principal | One session behind |
| [Sikafinance](https://www.sikafinance.com/) | Beta, RSI, % of capital traded, dividend history, dated headlines, investor poll | 15 minutes delayed (Sikafinance's own notice) |

This project is not affiliated with the BRVM or with Sikafinance, and the data belongs to them. The
server reads public pages when a tool is called, for research and personal use; it does not host
or redistribute a copy of them. brvm.org's legal notice reserves all reproduction rights, so check
each source's terms before you redistribute its data.

How the server treats its sources:
- **robots.txt is respected**: no request to a disallowed path. brvm.org's robots.txt asks for
  10 seconds between requests; the cache keeps repeated tool calls off the site, so avoid calling
  tools in a tight loop.
- **Caching**: 5 minutes per tool call, 1 hour for the BOC PDF.
- **Polite User-Agent** that names the project.
- **Public pages only**: no login and no paywall. Sikafinance's premium articles come back as
  headlines only.

For real-time FIX feeds, contact BRVM directly: [brvm.org/real-time-data-feed](https://www.brvm.org/en/real-time-data-feed)

## Contributing

Contributions are welcome, in English or French. Start with
[CONTRIBUTING.md](CONTRIBUTING.md): setup, checks, how to add a tool, and the rules for collecting
data. Issues labelled
[`good first issue`](https://github.com/Dilane-Kamga/brvm-mcp-server/labels/good%20first%20issue)
are a good way in.

Priority areas:
1. Historical data (OHLCV bars, roadmap v0.2)
2. Offline tests on saved pages (VCR cassettes) for the scrapers
3. Additional data sources, once their terms allow it
4. TypeScript port for Node.js MCP hosts

If the project is useful to you, a star on GitHub helps other people find it.

## Contributors

- [@AmadouAz](https://github.com/AmadouAz): brvm.org as the primary source, with the BOC PDF (#1);
  Sikafinance stock pages and news (#2).

## License

MIT

---

Built with ☕ in Mauritius by [Dilane Fogué Kamga](https://www.linkedin.com/in/dilane-fogue-kamga/) — Senior Software & AI Engineer, Financial Engineering MSc ([WorldQuant University](https://www.wqu.edu/mscfe)).

*Bridging AI and African capital markets.*
