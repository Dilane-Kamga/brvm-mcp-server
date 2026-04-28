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
