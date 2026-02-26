"""
Scraper Orchestrator

sahibinden ve arabam'ı paralel çalıştırır,
sonuçları birleştirir, duplikaları temizler.
"""
import asyncio
from typing import AsyncGenerator

from loguru import logger

from models.listing import CarListing, ScrapeFilter, Source
from scrapers.sahibinden import SahibindenScraper
from scrapers.arabam import ArabamScraper


# Uniq Auto'nun takip ettiği marka/segment kombinasyonları
DEFAULT_WATCH_FILTERS: list[ScrapeFilter] = [
    # === ORTA SEGMENT (500K - 1.5M) ===
    ScrapeFilter(
        brands=["BMW"],
        price_min=500_000,
        price_max=1_500_000,
        year_min=2016,
        km_max=150_000,
    ),
    ScrapeFilter(
        brands=["Mercedes"],
        price_min=500_000,
        price_max=1_500_000,
        year_min=2016,
        km_max=150_000,
    ),
    ScrapeFilter(
        brands=["Audi"],
        price_min=500_000,
        price_max=1_500_000,
        year_min=2016,
        km_max=150_000,
    ),
    ScrapeFilter(
        brands=["Volkswagen"],
        price_min=500_000,
        price_max=1_500_000,
        year_min=2018,
        km_max=120_000,
    ),
    # === PREMİUM SEGMENT (1.5M - 3M) ===
    ScrapeFilter(
        brands=["BMW"],
        price_min=1_500_000,
        price_max=3_000_000,
        year_min=2019,
        km_max=80_000,
    ),
    ScrapeFilter(
        brands=["Mercedes"],
        price_min=1_500_000,
        price_max=3_000_000,
        year_min=2019,
        km_max=80_000,
    ),
    ScrapeFilter(
        brands=["Porsche"],
        price_min=1_500_000,
        price_max=3_000_000,
        year_min=2017,
        km_max=60_000,
    ),
    ScrapeFilter(
        brands=["Volvo"],
        price_min=1_500_000,
        price_max=3_000_000,
        year_min=2019,
        km_max=80_000,
    ),
]


class ScraperOrchestrator:
    """
    Tüm scraper'ları koordine eder:
    - Paralel çalıştırma
    - Duplikasyon tespiti
    - Hata izolasyonu (bir scraper çökerse diğeri devam eder)
    """

    def __init__(self, sources: list[Source] | None = None):
        self.sources = sources or [Source.SAHIBINDEN, Source.ARABAM]
        self._seen_ids: set[str] = set()  # Duplikat önleme

    async def run_all_filters(
        self,
        filters: list[ScrapeFilter] | None = None,
        on_listing=None,
    ) -> list[CarListing]:
        """
        Tüm filtreleri her iki sitede çalıştırır.
        on_listing callback ile her ilan geldiğinde aksiyonu tetikle.
        
        Returns: Tüm benzersiz ilanlar
        """
        filters = filters or DEFAULT_WATCH_FILTERS
        all_listings: list[CarListing] = []
        self._seen_ids.clear()

        logger.info(f"Orchestrator başlatıldı — {len(filters)} filtre, {len(self.sources)} kaynak")

        for i, filter in enumerate(filters):
            logger.info(f"Filtre {i+1}/{len(filters)}: {filter.brands} | {filter.price_min:,}-{filter.price_max:,} TL")

            # Her filtre için iki siteyi paralel çalıştır
            tasks = []
            if Source.SAHIBINDEN in self.sources:
                tasks.append(self._collect_from_source(SahibindenScraper(), filter))
            if Source.ARABAM in self.sources:
                tasks.append(self._collect_from_source(ArabamScraper(), filter))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Scraper hatası: {result}")
                    continue
                for listing in result:
                    if listing.id not in self._seen_ids:
                        self._seen_ids.add(listing.id)
                        all_listings.append(listing)
                        if on_listing:
                            await on_listing(listing)

            # Filtreler arası bekleme
            if i < len(filters) - 1:
                await asyncio.sleep(5)

        logger.success(f"Tamamlandı — {len(all_listings)} benzersiz ilan")
        return all_listings

    async def _collect_from_source(
        self, scraper, filter: ScrapeFilter
    ) -> list[CarListing]:
        """Tek bir scraper + filtre kombinasyonunu çalıştırır, listeye toplar"""
        listings = []
        try:
            async for listing in scraper.scrape_listings(filter):
                listings.append(listing)
        except Exception as e:
            logger.error(f"[{scraper.source_name}] toplama hatası: {e}")
        return listings

    def deduplicate_cross_source(
        self, listings: list[CarListing]
    ) -> list[CarListing]:
        """
        Aynı araç farklı sitelerde olabilir.
        Yıl + KM + fiyat yakınlığı ile tespit et.
        """
        unique = []
        seen_fingerprints: set[str] = set()

        for listing in listings:
            # KM'i 5000'e yuvarlayarak tolerans ekle
            km_rounded = round(listing.km / 5000) * 5000
            # Fiyatı %2'ye yuvarlayarak tolerans ekle
            price_rounded = round(listing.price / 50000) * 50000

            fingerprint = f"{listing.brand}_{listing.model}_{listing.year}_{km_rounded}_{price_rounded}"

            if fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                unique.append(listing)
            else:
                logger.debug(f"Cross-source duplikat tespit edildi: {listing.title}")

        removed = len(listings) - len(unique)
        if removed:
            logger.info(f"{removed} cross-source duplikat kaldırıldı")

        return unique
