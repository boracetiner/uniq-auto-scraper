from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from enum import Enum


class Segment(str, Enum):
    ORTA = "orta"        # 500K - 1.5M
    PREMIUM = "premium"  # 1.5M - 3M


class Source(str, Enum):
    SAHIBINDEN = "sahibinden"
    ARABAM = "arabam"


class CarListing(BaseModel):
    """Ham ilan verisi — scraper'dan çıkan"""
    id: str
    source: Source
    url: str
    title: str
    brand: str
    model: str
    series: Optional[str] = None     # Örn: "3 Serisi", "C Serisi"
    year: int
    km: int
    price: int                        # TL cinsinden
    color: Optional[str] = None
    fuel_type: Optional[str] = None  # Benzin, Dizel, Elektrik, Hibrit
    gear_type: Optional[str] = None  # Manuel, Otomatik
    body_type: Optional[str] = None  # Sedan, SUV, Hatchback
    location: str
    seller_type: Optional[str] = None  # Galeriden, Sahibinden
    seller_id: Optional[str] = None
    images: list[str] = []
    listed_at: Optional[datetime] = None
    scraped_at: datetime = None
    is_active: bool = True

    @field_validator("price", "km", "year", mode="before")
    @classmethod
    def clean_numeric(cls, v):
        if isinstance(v, str):
            cleaned = "".join(c for c in v if c.isdigit())
            return int(cleaned) if cleaned else 0
        return v

    @field_validator("scraped_at", mode="before")
    @classmethod
    def set_scraped_at(cls, v):
        return v or datetime.now()

    @property
    def segment(self) -> Optional[Segment]:
        if 500_000 <= self.price <= 1_500_000:
            return Segment.ORTA
        elif 1_500_000 < self.price <= 3_000_000:
            return Segment.PREMIUM
        return None


class OpportunityResult(BaseModel):
    """Fiyat motoru çıktısı"""
    listing: CarListing
    fair_value: float
    market_median: float
    market_min: float
    market_max: float
    discount_amount: float
    discount_pct: float
    opportunity_score: float          # 0-100
    confidence: str                   # "high", "medium", "low"
    sample_size: int
    comparable_listings: list[str] = []  # URL listesi


class ScrapeFilter(BaseModel):
    """Scraper'a verilen filtre"""
    brands: list[str] = []
    models: list[str] = []
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    km_max: Optional[int] = None
    fuel_types: list[str] = []
    gear_types: list[str] = []
    location: Optional[str] = None
