import re
import time
import random
import httpx
from datetime import datetime
from loguru import logger
from models.listing import CarListing, ScrapeFilter, Source
import os

BASE_URL = "https://www.arabam.com"
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

def scraper_api_url(target_url: str) -> str:
    return f"https://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&country_code=tr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

BRAND_SLUGS = {
    "BMW": "bmw",
    "Mercedes": "mercedes-benz",
    "Audi": "audi",
    "Volkswagen": "volkswagen",
    "Porsche": "porsche",
    "Volvo": "volvo",
}

class ArabamLightScraper:
    def __init__(self):
        self.client = httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def scrape_listings(self, filter: ScrapeFilter) -> list[CarListing]:
        from bs4 import BeautifulSoup
        all_listings = []

        for page_num in range(1, 4):
            url = self._build_url(filter, page_num)
            api_url = scraper_api_url(url)
            logger.info(f"[Arabam] Sayfa {page_num}")

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
                logger.success(f"Sayfa {page_num}: {len(items)} ilan")

                if len(items) < 10:
                    break

            except Exception as e:
                logger.error(f"Arabam hata: {e}")
                break

        return all_listings

    def _build_url(self, filter: ScrapeFilter, page: int) -> str:
        path = "ikinci-el/otomobil"
        if filter.brands:
            slug = BRAND_SLUGS.get(filter.brands[0], filter.brands[0].lower())
            path = f"ikinci-el/otomobil/{slug}"

        params = [f"page={page}", "sort=0", "take=50"]
        if filter.price_min:
            params.append(f"minPrice={filter.price_min}")
        if filter.price_max:
            params.append(f"maxPrice={filter.price_max}")
        if filter.year_min:
            params.append(f"minYear={filter.year_min}")
        if filter.km_max:
            params.append(f"maxKm={filter.km_max}")

        return f"{BASE_URL}/{path}?{'&'.join(params)}"

    def _parse_page(self, soup, filter: ScrapeFilter) -> list[CarListing]:
        listings = []
        rows = soup.select("tr[data-listing-id], .listing-list-item, tr.listing-item")
        for row in rows:
            try:
                listing = self._parse_row(row, filter)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Row parse hatası: {e}")
        return listings

    def _parse_row(self, row, filter: ScrapeFilter) -> CarListing | None:
        listing_id = row.get("data-listing-id") or row.get("data-id", "")
        link_el = row.select_one("a[href*='/ilan/'], .listing-title a, td a")
        if not link_el:
            return None

        url = link_el.get("href", "")
        if url and not url.startswith("http"):
            url = f"{BASE_URL}{url}"

        title = link_el.get_text(strip=True)

        if not listing_id:
            m = re.search(r"/ilan/(\d+)", url)
            listing_id = m.group(1) if m else url

        price_el = row.select_one(".listing-price, [data-price], .price-container")
        price_raw = ""
        if price_el:
            price_raw = price_el.get("data-price") or price_el.get_text()
        price = self._clean_int(price_raw)

        if price == 0:
            return None
        if filter.price_min and price < filter.price_min:
            return None
        if filter.price_max and price > filter.price_max:
            return None

        attrs = [el.get_text(strip=True) for el in row.select("td, .listing-info span")]
        year = self._extract_year(attrs, title)
        km = self._extract_km(attrs)

        loc_el = row.select_one(".listing-location, [class*='location']")
        location = loc_el.get_text(strip=True) if loc_el else ""

        brand = filter.brands[0] if filter.brands else ""
        model = self._extract_model(title, brand)

        return CarListing(
            id=f"arabam_{listing_id}",
            source=Source.ARABAM,
            url=url,
            title=title,
            brand=brand,
            model=model,
            year=year,
            km=km,
            price=price,
            location=location,
            scraped_at=datetime.now(),
        )

    def _clean_int(self, raw: str) -> int:
        digits = re.sub(r"[^\d]", "", str(raw))
        return int(digits) if digits else 0

    def _extract_year(self, attrs, title=""):
        for a in list(attrs) + [title]:
            m = re.search(r"\b(19|20)\d{2}\b", str(a))
            if m:
                return int(m.group())
        return 0

    def _extract_km(self, attrs):
        for a in attrs:
            if "km" in a.lower():
                val = self._clean_int(a)
                if 0 < val < 2_000_000:
                    return val
        return 0

    def _extract_model(self, title, brand):
        if brand and title.startswith(brand):
            rest = title[len(brand):].strip().split()
            return rest[0] if rest else ""
        parts = title.split()
        return parts[1] if len(parts) > 1 else ""
