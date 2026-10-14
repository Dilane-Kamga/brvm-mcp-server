# Contributing to brvm-mcp-server

Thanks for helping. This server gives AI agents access to market data from the BRVM, the regional
stock exchange of the 8 UEMOA countries. Contributions in English or French are both welcome, in
issues, pull requests and code comments.

By taking part, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Where to start

- Issues labelled [`good first issue`](https://github.com/Dilane-Kamga/brvm-mcp-server/labels/good%20first%20issue)
  are small and self-contained.
- [`help wanted`](https://github.com/Dilane-Kamga/brvm-mcp-server/labels/help%20wanted) marks larger
  work, often from the [roadmap](README.md#roadmap).
- Before building a new tool or adding a data source, open an issue first (there is a template for
  each). It avoids writing a scraper for a site whose rules forbid it.

## Set up

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Dilane-Kamga/brvm-mcp-server.git
cd brvm-mcp-server
uv sync --extra dev
```

## Check your change

CI runs these three commands on Python 3.11, 3.12 and 3.13. Run them before you open a pull request:

```bash
uv run ruff check src/ tests/   # lint (line length 100)
uv run mypy src/                # type check
uv run pytest                   # offline tests only
```

`uv run pytest` skips two groups of tests on purpose:

- `live` tests call brvm.org or sikafinance.com. Run them with `uv run pytest -m live` when you
  change a scraper, and not in a loop: brvm.org's robots.txt asks for 10 seconds between requests.
- `stress` tests start a local HTTP server and load it. Run them with `uv run pytest -m stress`.

Any test that sends a request to a real site must carry `@pytest.mark.live`. Tests that parse
saved HTML or mocked responses need no marker and run in CI.

## Adding a tool

1. Add the Pydantic model in `src/brvm_mcp/models/__init__.py`.
2. Add the scraper method in `src/brvm_mcp/scrapers/` (`__init__.py` for brvm.org,
   `sikafinance.py` for Sikafinance, or a new module for a new source).
3. Add the tool in `src/brvm_mcp/server.py` with the `@mcp.tool()` decorator.
4. Write the docstring for the agent: it becomes the tool description. Say what each parameter
   does and what the JSON looks like.
5. Go through the cache: check the cache, then scrape, then store the result.
6. Return errors as JSON objects (`{"error": "..."}`), never as raised exceptions, so the agent can
   handle them.
7. Add tests: offline tests on saved HTML, and `live` tests against the real page.
8. Update the tool table in `README.md` and the tool count in `CLAUDE.md`.

Code style: type hints everywhere, `X | None` rather than `Optional[X]`, async for all I/O, Pydantic
models for anything that crosses a boundary.

## Rules for collecting data

These rules protect the sources the project depends on. A pull request that breaks one of them will
not be merged, however good the code is.

- **Respect robots.txt.** Check the site's `robots.txt` before scraping a new path. A path under
  `Disallow` stays out of the project.
- **Be polite.** Use the project's User-Agent, go through the cache (5 minutes by default, longer for
  data that changes once a day), and never send requests in parallel to the same site.
- **No paywall bypass, no login.** Read only what a visitor sees without an account. Sikafinance's
  "Sika Premium" articles are returned as headlines with `is_premium: true`, nothing more.
- **No invented data.** If a source does not publish a field, the tool returns nothing for it.
- **No secrets in code.** Use environment variables.

## Pull requests

- One topic per pull request. If your work depends on another open pull request, say so in the
  description.
- Keep your own commits: maintainers merge with a merge commit, so authorship is preserved.
- Fill in the pull request template, including how you tested against the real site.
