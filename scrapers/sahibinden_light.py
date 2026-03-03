import re
import time
import random
import httpx
from datetime import datetime
from loguru import logger
from models.listing import CarListing, ScrapeFilter, Source
import os

BASE_URL = "https://www.sahibinden.com"
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

def scraper_api_url(target_url: str) -> str:
    return f"https://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&country_code=tr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

BRAND_SLUGS = {
    "BMW": "otomobil-bmw",
    "Mercedes": "otomobil-mercedes_benz",
    "Audi": "otomobil-audi",
    "Volkswagen": "otomobil-volkswagen",
    "Porsche": "otomobil-porsche",
    "Volvo": "otomobil-volvo",
}

class SahibindenLightScraper:
    def __init__(self):
        self.client = httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def scrape_listings(self, filter: ScrapeFilter) -> list[CarListing]:
        from bs4 import BeautifulSoup
        all_listings = []

        for page_num in range(3):
            url = self._build_url(filter, page_num)
            api_url = scraper_api_url(url)
            logger.info(f"[Sahibinden] Sayfa {page_num + 1}")

            try:
                time.sleep(random.uniform(1, 2))
                resp = self.client.get(api_url)

                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                items = self._parse_page(soup, filter)

                if not items:
                    break

                all_listings.extend(items)
                logger.success(f"Sayfa {page_num + 1}: {len(items)} ilan")

                if len(items) < 20:
                    break

            except Exception as e:
                logger.error(f"Hata: {e}")
                break

        return all_listings

    def _build_url(self, filter: ScrapeFilter, page: int) -> str:
        params = []
        if filter.price_min:
            params.append(f"price_min={filter.price_min}")
        if filter.price_max:
            params.append(f"price_max={filter.price_max}")
        if filter.year_min:
            params.append(f"year_min={filter.year_min}")
        if filter.km_max:
            params.append(f"km_max={filter.km_max}")
        params.append(f"pagingOffset={page * 50}")
        params.append("sorting=date_desc")
        query = "&".join(params)

        if filter.brands:
            slug = BRAND_SLUGS.get(filter.brands[0], "otomobil")
            return f"{BASE_URL}/{slug}?{query}"
        return f"{BASE_URL}/otomobil?{query}"

    def _parse_page(self, soup, filter: ScrapeFilter) -> list[CarListing]:
        listings = []
        rows = soup.select("tr.searchResultsItem")
        for row in rows:
            try:
                listing = self._parse_row(row, filter)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Row parse hatası: {e}")
        return listings

    def _parse_row(self, row, filter: ScrapeFilter) -> CarListing | None:
        listing_id = row.get("data-id", "")
        if not listing_id:
            return None

        title_el = row.select_one("a.classifiedTitle")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        url = title_el.get("href", "")
        if url and not url.startswith("http"):
            url = f"{BASE_URL}{url}"

        price_el = row.select_one(".price-container span, .classified-price")
        price = self._clean_int(price_el.get_text() if price_el else "0")
        if price == 0:
            return None

        if filter.price_min and price < filter.price_min:
            return None
        if filter.price_max and price > filter.price_max:
            return None

        attrs = [el.get_text(strip=True) for el in row.select(".searchResultsAttributeValue")]
        year = self._extract_year(attrs)
        km = self._extract_km(attrs)
        color = attrs[2] if len(attrs) > 2 else None
        fuel_type = attrs[3] if len(attrs) > 3 else None
        gear_type = attrs[4] if len(attrs) > 4 else None

        loc_el = row.select_one(".searchResultsLocationValue")
        location = loc_el.get_text(strip=True) if loc_el else ""

        brand = filter.brands[0] if filter.brands else ""
        model = self._extract_model(title, brand)

        return CarListing(
            id=f"sahibinden_{listing_id}",
            source=Source.SAHIBINDEN,
            url=url,
            title=title,
            brand=brand,
            model=model,
            year=year,
            km=km,
            price=price,
            color=color,
            fuel_type=fuel_type,
            gear_type=gear_type,
            location=location,
            scraped_at=datetime.now(),
        )

    def _clean_int(self, raw: str) -> int:
        digits = re.sub(r"[^\d]", "", str(raw))
        return int(digits) if digits else 0

    def _extract_year(self, attrs):
        for a in attrs:
            m = re.search(r"\b(19|20)\d{2}\b", a)
            if m:
                return int(m.group())
        return 0

    def _extract_km(self, attrs):
        for a in attrs:
            if "km" in a.lower() or re.search(r"\d{3,}", a):
                val = self._clean_int(a)
                if 0 < val < 2_000_000:
                    return val
        return 0

    def _extract_model(self, title, brand):
        if brand and title.startswith(brand):
            rest = title[len(brand):].strip().split()
            return rest[0] if rest else ""
        return title.split()[1] if len(title.split()) > 1 else ""
