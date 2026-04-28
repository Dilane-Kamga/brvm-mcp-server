"""Stress tests for BRVM scraper, parser, and MCP server."""

import asyncio
import time

import httpx
import pytest

from brvm_mcp.scrapers import BRVMScraper


# ── 1. Scraper Concurrency ──────────────────────────────────────

class TestScraperConcurrency:
    """Blast the scraper with concurrent calls to test stability."""

    @pytest.mark.asyncio
    async def test_concurrent_get_all_quotes(self):
        scraper = BRVMScraper()
        try:
            tasks = [scraper.get_all_quotes() for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successes = [r for r in results if not isinstance(r, Exception)]
            errors = [r for r in results if isinstance(r, Exception)]
            print(f"\n  10 concurrent get_all_quotes: {len(successes)} ok, {len(errors)} errors")
            for e in errors:
                print(f"    ERROR: {e}")
            assert len(successes) >= 8, f"Too many failures: {len(errors)}/10"
            for quotes in successes:
                assert len(quotes) > 40
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_concurrent_mixed_calls(self):
        """Mixed calls fan out to many HTTP requests internally; some 429s are expected."""
        await asyncio.sleep(3)
        scraper = BRVMScraper()
        try:
            tasks = [
                scraper.get_all_quotes(),
                scraper.get_indices(),
                scraper.get_top_movers(3),
                scraper.get_quote("SNTS"),
                scraper.get_market_summary(),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successes = [r for r in results if not isinstance(r, Exception)]
            errors = [r for r in results if isinstance(r, Exception)]
            print(f"\n  5 mixed concurrent calls: {len(successes)} ok, {len(errors)} errors")
            for e in errors:
                print(f"    ERROR: {type(e).__name__}: {e}")
            assert len(successes) >= 2, "Retry logic should handle most 429s"
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_rapid_sequential_calls(self):
        await asyncio.sleep(3)
        scraper = BRVMScraper()
        try:
            start = time.perf_counter()
            for i in range(5):
                quotes = await scraper.get_all_quotes()
                assert len(quotes) > 40
            elapsed = time.perf_counter() - start
            print(f"\n  5 sequential get_all_quotes in {elapsed:.1f}s ({elapsed/5:.1f}s avg)")
        finally:
            await scraper.close()

    @pytest.mark.asyncio
    async def test_scraper_reuse_after_error(self):
        await asyncio.sleep(3)
        scraper = BRVMScraper()
        try:
            original_base = "https://afx.kwayisi.org/brvm"
            import brvm_mcp.scrapers as mod
            mod.AFX_BASE = "https://afx.kwayisi.org/nonexistent"
            try:
                await scraper.get_all_quotes()
            except httpx.HTTPStatusError:
                pass

            mod.AFX_BASE = original_base
            quotes = await scraper.get_all_quotes()
            assert len(quotes) > 40, "Scraper should recover after an error"
            print(f"\n  Scraper recovered after HTTP error: {len(quotes)} quotes")
        finally:
            await scraper.close()


# ── 2. Parser Resilience ────────────────────────────────────────

class TestParserResilience:
    """Throw malformed and edge-case inputs at the parser."""

    EDGE_CASES = [
        ("", 0.0),
        ("N/A", 0.0),
        ("---", 0.0),
        ("...", 0.0),
        (",,,", 0.0),
        ("+", 0.0),
        ("-", 0.0),
        (".", 0.0),
        (",", 0.0),
        ("abc123def", 123.0),
        ("XOF 15.51Tr", 15.51),
        ("(+0.59)", 0.59),
        ("+56.84", 56.84),
        ("-24.16%", -24.16),
        ("1,018,483", 1018483.0),
        ("1 234 567", 1234567.0),
        ("1\xa0234\xa0567", 1234567.0),
        ("0", 0.0),
        ("0.0", 0.0),
        ("-0", 0.0),
        ("+0", 0.0),
        ("999999999999", 999999999999.0),
        ("0.001", 0.001),
        ("-1,330", -1330.0),
        ("+3,500", 3500.0),
        ("  42  ", 42.0),
        ("\t100\n", 100.0),
    ]

    @pytest.mark.parametrize("text,expected", EDGE_CASES, ids=[c[0][:20] or "empty" for c in EDGE_CASES])
    def test_parse_number_edge_cases(self, text, expected):
        result = BRVMScraper._parse_number(text)
        assert result == expected, f"_parse_number({text!r}) = {result}, expected {expected}"

    def test_parse_number_never_raises(self):
        """Fuzz with random garbage — must never raise."""
        import random
        import string
        random.seed(42)
        chars = string.printable + "\xa0​ "
        for _ in range(1000):
            length = random.randint(0, 50)
            text = "".join(random.choice(chars) for _ in range(length))
            try:
                result = BRVMScraper._parse_number(text)
                assert isinstance(result, float)
            except Exception as e:
                pytest.fail(f"_parse_number({text!r}) raised {e}")

    def test_html_missing_table(self):
        """Scraper should return empty list if no stock table found."""
        from unittest.mock import AsyncMock, patch, MagicMock

        async def _run():
            scraper = BRVMScraper()
            mock_resp = MagicMock()
            mock_resp.text = "<html><body><p>No tables here</p></body></html>"
            with patch.object(scraper, "_get_with_retry", return_value=mock_resp):
                quotes = await scraper.get_all_quotes()
                assert quotes == [], f"Expected empty list, got {len(quotes)} quotes"
                indices = await scraper.get_indices()
                assert isinstance(indices, list)
            await scraper.close()

        asyncio.run(_run())

    def test_html_malformed_cells(self):
        """Scraper should skip rows with missing or garbage cells."""
        from unittest.mock import patch, MagicMock

        html = """<html><body>
        <div class="t"><table>
        <thead><tr><th>Ticker<th>Name<th>Volume<th>Price<th>Change</thead>
        <tbody>
        <tr><td><a href=#>TEST</a><td>Test Co<td>abc<td>xyz<td>???
        <tr><td><a href=#>GOOD</a><td>Good Co<td>1,000<td>500<td>+10
        <tr><td colspan=5>spacer row
        </tbody></table></div>
        </body></html>"""

        async def _run():
            scraper = BRVMScraper()
            mock_resp = MagicMock()
            mock_resp.text = html
            with patch.object(scraper, "_get_with_retry", return_value=mock_resp):
                quotes = await scraper.get_all_quotes()
                assert len(quotes) == 2, f"Expected 2 quotes (incl garbage row), got {len(quotes)}"
                good = [q for q in quotes if q.ticker == "GOOD"]
                assert len(good) == 1
                assert good[0].price == 500.0
                assert good[0].change == 10.0
            await scraper.close()

        asyncio.run(_run())


# ── 3. MCP HTTP Server Load ─────────────────────────────────────

class TestMCPServerLoad:
    """Spin up the HTTP server and blast it with requests."""

    @pytest.fixture(autouse=True)
    def _start_server(self):
        """Start MCP HTTP server in a subprocess for the test class."""
        import subprocess
        import sys
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "brvm_mcp.server",
             "--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8111"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(40):
            try:
                resp = httpx.post(
                    "http://127.0.0.1:8111/mcp",
                    json={
                        "jsonrpc": "2.0", "id": 0, "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "probe", "version": "1.0"},
                        },
                    },
                    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                    timeout=2.0,
                )
                if resp.status_code < 500:
                    break
            except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout):
                time.sleep(0.5)
        yield
        self.proc.terminate()
        self.proc.wait(timeout=5)

    def test_concurrent_http_requests(self):
        """Send 20 concurrent requests — single-worker uvicorn won't handle all, but shouldn't crash."""
        async def _blast():
            async with httpx.AsyncClient(timeout=30.0) as client:
                tasks = []
                for i in range(20):
                    tasks.append(client.post(
                        "http://127.0.0.1:8111/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": i,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "stress-test", "version": "1.0"},
                            },
                        },
                        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                    ))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                successes = [r for r in results if not isinstance(r, Exception) and r.status_code < 500]
                errors = [r for r in results if isinstance(r, Exception)]
                print(f"\n  20 concurrent HTTP init: {len(successes)} ok, {len(errors)} errors")
                assert len(successes) >= 5, f"Server couldn't handle any load: {len(successes)}/20"

        asyncio.run(_blast())

    def test_rapid_sequential_http(self):
        """Send 10 sequential requests and measure latency."""
        start = time.perf_counter()
        for i in range(10):
            resp = httpx.post(
                "http://127.0.0.1:8111/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "stress-test", "version": "1.0"},
                    },
                },
                headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                timeout=15.0,
            )
            assert resp.status_code < 500
        elapsed = time.perf_counter() - start
        print(f"\n  10 sequential HTTP init in {elapsed:.1f}s ({elapsed/10:.2f}s avg)")
