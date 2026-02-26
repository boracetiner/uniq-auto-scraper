"""
Scraper Orchestrator — Light versiyon (Playwright yok)
"""
from models.listing import ScrapeFilter

DEFAULT_WATCH_FILTERS = [
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
