# 🇨🇮 BRVM MCP Server

**The first MCP server for West Africa's regional stock exchange.**

Connect any AI agent — Claude, ChatGPT, Cursor, Copilot, LangGraph — to live market data from the [BRVM](https://www.brvm.org/) (Bourse Régionale des Valeurs Mobilières), serving 8 UEMOA member states across West Africa.

![MCP](https://img.shields.io/badge/MCP-1.27+-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Why?

The BRVM lists ~46 companies across Bénin, Burkina Faso, Côte d'Ivoire, Guinée-Bissau, Mali, Niger, Sénégal, and Togo — with a combined market cap of ~$27.8B USD. Yet it has **no public API**. This server bridges that gap, making BRVM data accessible to the AI ecosystem via the [Model Context Protocol](https://modelcontextprotocol.io).

### What's coming on the BRVM
- **December 18, 2026**: First derivatives market in francophone West Africa (futures on indices and stocks)
- **2026–2027**: ETF listings
- **2026**: Agricultural commodities exchange (BMPA CI) — cashew, maize, cola nut

This server is built to grow alongside these developments.

## Features

### Tools (7)
| Tool | Description |
|------|-------------|
| `get_market_summary` | Full trading session overview: volume, value, gainers/losers, indices |
| `get_stock_price` | Current quote for a specific ticker (price, change, volume) |
| `get_indices` | All BRVM indices: Composite, BRVM 30, Prestige, Principal, sectors |
| `get_top_movers` | Top N gainers and losers of the day |
| `get_company_info` | Company details: name, country, sector, market cap |
| `search_stocks` | Search by name, country, or sector |
| `list_tickers` | All ~46 BRVM tickers with metadata |

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
git clone https://github.com/dilanefk/brvm-mcp-server.git
cd brvm-mcp-server

# Install
uv sync

# Run (stdio — for Claude Desktop / Cursor)
uv run brvm-mcp

# Run (HTTP — for remote agents / web apps)
uv run brvm-mcp --transport streamable-http --port 8000
```

### Connect to Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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

Restart Claude Desktop. You'll see the BRVM tools in the 🔨 menu.

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
                                              ┌────────▼─────────┐
                                              │  Data Sources    │
                                              │  • afx.kwayisi   │
                                              │  • brvm.org      │
                                              │  • Rich Bourse   │
                                              └──────────────────┘
```

- **FastMCP**: Decorator-based MCP framework (official Python SDK)
- **httpx**: Async HTTP client for scraping
- **BeautifulSoup4 + lxml**: HTML parsing
- **diskcache**: TTL-based disk caching (5min default, respectful of sources)
- **Pydantic**: Structured data models

## Roadmap

- [ ] **v0.2** — Historical price data (OHLCV bars)
- [ ] **v0.3** — BRVM official announcements / corporate actions feed
- [ ] **v0.4** — BMPA CI commodities data (when available)
- [ ] **v0.5** — Derivatives data (futures, options — post Dec 2026 launch)
- [ ] **v1.0** — OAuth + rate limiting for multi-user deployment
- [ ] Register on [MCP Registry](https://registry.modelcontextprotocol.io)

## Data Sources & Fair Use

This server scrapes publicly available data. It implements:
- **Caching** (5min TTL) to minimize requests
- **Polite User-Agent** header identifying the project
- **No authentication bypass** — only public data

For real-time FIX feeds, contact BRVM directly: [brvm.org/real-time-data-feed](https://www.brvm.org/en/real-time-data-feed)

## Contributing

PRs welcome! Priority areas:
1. Additional data sources (eodhd.com, Rich Bourse)
2. Historical data support
3. Tests (pytest + VCR cassettes for scraper tests)
4. TypeScript port for Node.js MCP hosts

## License

MIT

---

Built with ☕ in Mauritius by [Dilane Fogué Kamga](https://www.linkedin.com/in/dilane-fogue-kamga/) — Senior Software & AI Engineer, Financial Engineering MSc ([WorldQuant University](https://www.wqu.edu/mscfe)).

*Bridging AI and African capital markets.*
