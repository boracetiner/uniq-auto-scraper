"""
Fiyat Motoru

Benzer araçların veritabanı ortalamasına göre
fırsat skoru hesaplar.
"""
import statistics
from typing import Optional

from loguru import logger

from models.listing import CarListing, OpportunityResult


class PriceEngine:

    def __init__(self, db):
        self.db = db

    def evaluate(self, listing: CarListing) -> Optional[OpportunityResult]:
        """
        Tek bir ilanı değerlendirir.
        Karşılaştırma için yeterli veri yoksa None döner.
        """
        if not listing.brand or not listing.model or listing.price == 0:
            return None

        comparables = self.db.get_comparables(
            brand=listing.brand,
            model=listing.model,
            year=listing.year,
            km=listing.km,
        )

        if len(comparables) < 3:
            return None  # Güvenilir karşılaştırma için min 3 araç

        prices = [c["price"] for c in comparables]

        median = statistics.median(prices)
        market_min = statistics.quantiles(prices, n=10)[0]  # %10 percentil
        market_max = statistics.quantiles(prices, n=10)[8]  # %90 percentil

        # KM düzeltmesi: her 10.000 km için ~%2.5 fiyat farkı
        km_diff = listing.km - statistics.mean([c["km"] for c in comparables])
        km_correction = median * (km_diff / 10_000) * -0.025
        fair_value = median + km_correction

        discount_amount = fair_value - listing.price
        discount_pct = (discount_amount / fair_value) * 100 if fair_value > 0 else 0

        # Skor hesapla: %15 indirim → 45 puan, %30 → 90 puan
        score = min(100, max(0, discount_pct * 3))

        confidence = (
            "high" if len(comparables) >= 20
            else "medium" if len(comparables) >= 8
            else "low"
        )

        return OpportunityResult(
            listing=listing,
            fair_value=fair_value,
            market_median=median,
            market_min=market_min,
            market_max=market_max,
            discount_amount=discount_amount,
            discount_pct=discount_pct,
            opportunity_score=score,
            confidence=confidence,
            sample_size=len(comparables),
            comparable_listings=[c["url"] for c in comparables[:5]],
        )
