## What this changes

<!-- One or two sentences. Link the issue if there is one: "Closes #12". -->

## How I tested it

- [ ] `uv run ruff check src/ tests/`
- [ ] `uv run mypy src/`
- [ ] `uv run pytest`
- [ ] `uv run pytest -m live` (if a scraper changed), on <!-- date -->

## Data collection

- [ ] Every new path is allowed by the site's robots.txt
- [ ] New requests go through the cache and use the project's User-Agent
- [ ] No login, no paywall bypass, no invented fields
- [ ] Not applicable: this change does not touch data collection

## Docs

- [ ] README tool table and the tool count in `CLAUDE.md` are up to date (if a tool was added)
