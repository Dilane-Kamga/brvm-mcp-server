"""Pydantic models for BRVM market data."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Country(str, Enum):
    BENIN = "Bénin"
    BURKINA_FASO = "Burkina Faso"
    COTE_DIVOIRE = "Côte d'Ivoire"
    GUINEA_BISSAU = "Guinée-Bissau"
    MALI = "Mali"
    NIGER = "Niger"
    SENEGAL = "Sénégal"
    TOGO = "Togo"


class Sector(str, Enum):
    AGRICULTURE = "Agriculture"
    DISTRIBUTION = "Distribution"
    FINANCE = "Services Financiers"
    INDUSTRY = "Industrie"
    PUBLIC_UTILITIES = "Services Publics"
    TRANSPORT = "Transport"
    OTHER = "Autres"


class StockQuote(BaseModel):
    """Real-time or end-of-day quote for a single ticker."""

    ticker: str = Field(..., description="BRVM ticker symbol, e.g. SNTS, ONTBF")
    name: str = Field(..., description="Full company name")
    price: float = Field(..., description="Last traded price in XOF")
    change: float = Field(0.0, description="Absolute price change vs previous close")
    change_pct: float = Field(0.0, description="Percentage change vs previous close")
    volume: int = Field(0, description="Number of shares traded")
    value_traded: float = Field(0.0, description="Total value traded in XOF")
    previous_close: float = Field(0.0, description="Previous session closing price")
    market_cap: float | None = Field(None, description="Market capitalization in XOF")
    country: str = Field("", description="Country of the listed company")
    sector: str = Field("", description="Industry sector")
    as_of: str = Field("", description="Data timestamp (ISO format or date)")


class IndexValue(BaseModel):
    """Value snapshot for a BRVM index."""

    name: str = Field(..., description="Index name, e.g. BRVM Composite, BRVM 30")
    value: float = Field(..., description="Current index value")
    change: float = Field(0.0, description="Absolute change")
    change_pct: float = Field(0.0, description="Percentage change")
    ytd_change_pct: float | None = Field(None, description="Year-to-date % change")
    as_of: str = Field("", description="Data timestamp")


class MarketSummary(BaseModel):
    """Aggregate BRVM trading session summary."""

    date: str = Field(..., description="Trading date")
    total_volume: int = Field(0, description="Total shares traded")
    total_value: float = Field(0.0, description="Total value traded in XOF")
    market_cap: float = Field(0.0, description="Total market capitalization in XOF")
    gainers: int = Field(0, description="Number of stocks that gained")
    losers: int = Field(0, description="Number of stocks that declined")
    unchanged: int = Field(0, description="Number of unchanged stocks")
    indices: list[IndexValue] = Field(default_factory=list)


class TopMover(BaseModel):
    """A stock appearing in top gainers or top losers."""

    ticker: str
    name: str
    price: float
    change_pct: float
    volume: int


class CompanyInfo(BaseModel):
    """Static company information."""

    ticker: str
    name: str
    country: str
    sector: str
    listing_section: str = Field("", description="BRVM listing section (1st or 2nd)")
    isin: str = Field("", description="ISIN code if available")
    market_cap: float | None = None
    description: str = ""


class HistoricalBar(BaseModel):
    """Single OHLCV bar for historical data."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    ticker: str


# ── Sikafinance (third-party analysis source) ───────────────────────
#
# brvm.org and the BOC give us official prices and volumes but no
# technical indicators, no investor sentiment, and no dated news feed.
# Sikafinance's per-ticker page fills exactly that gap — see
# scrapers/sikafinance.py for the source and freshness notes.


class SikaNewsItem(BaseModel):
    """One dated news headline from a Sikafinance ticker news feed."""

    date: str = Field(..., description="Publication date/time as shown, e.g. '02/09/26 18:53'")
    title: str = Field(..., description="Headline — usable as a web search query for full coverage")
    url: str = Field(..., description="Full URL to the article on sikafinance.com")
    is_premium: bool = Field(False, description="True if paywalled (Sika Premium) — headline only")


class SikaDividendEntry(BaseModel):
    """One year's dividend payout and yield, from a ticker's dividend history table."""

    year: str
    amount: float = Field(..., description="Gross dividend per share, in XOF")
    yield_pct: float | None = Field(None, description="Dividend yield at time of payout (%)")


class SikaHistoricalRange(BaseModel):
    """High/low/change over a rolling lookback window (1 week, 1 month, YTD, 1/3/5 years)."""

    period: str = Field(..., description="e.g. '1 semaine', '1 mois', '1er janvier' (YTD), '1 an'")
    high: float | None = Field(None, description="None if the stock isn't old enough for this")
    low: float | None = None
    change_pct: float | None = None


class SikaSentiment(BaseModel):
    """Investor sentiment poll on a ticker's page (self-reported votes, not a trade signal)."""

    buy_votes: int = 0
    sell_votes: int = 0
    hold_votes: int = 0

    @property
    def total_votes(self) -> int:
        return self.buy_votes + self.sell_votes + self.hold_votes


class SikaStockPage(BaseModel):
    """Full snapshot of a Sikafinance ticker page: quote + technicals + sentiment +
    recent news/filings + dividend and price-range history."""

    ticker: str
    name: str
    isin: str = ""
    country: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    value_traded: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    previous_close: float = 0.0
    beta_1y: float | None = Field(None, description="1-year beta vs the BRVM Composite")
    rsi: float | None = Field(None, description="14-day Relative Strength Index")
    capital_exchanged_pct: float | None = Field(None, description="% of share capital traded today")
    market_cap: float | None = Field(None, description="Market cap in millions of XOF (MXOF)")
    historical_ranges: list[SikaHistoricalRange] = Field(default_factory=list)
    dividends: list[SikaDividendEntry] = Field(default_factory=list)
    recent_news: list[SikaNewsItem] = Field(
        default_factory=list, description="Most recent headlines shown on the ticker page"
    )
    sentiment: SikaSentiment | None = None
    source_url: str = ""


class SikaFiling(BaseModel):
    """One row from Sikafinance's market-wide regulatory filings feed
    (communiqués BRVM) — not scoped to a single ticker."""

    date: str = Field(..., description="Publication date, e.g. '17/09/2026'")
    issuer: str = Field(..., description="Issuer name as printed before the ' _ ' separator")
    title: str = Field(..., description="Document title, e.g. 'Rapport d'activités - S1 2026'")
    pdf_url: str = Field(..., description="Direct URL to the filing PDF")
