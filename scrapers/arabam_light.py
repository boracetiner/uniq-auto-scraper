"""
Arabam.com hafif scraper — Playwright olmadan.
httpx + BeautifulSoup ile çalışır.
"""
import re
import time
import random
import httpx
from datetime import datetime
from loguru import logger
from models.listing import CarListing, ScrapeFilter, Source


BASE_URL = "https://www.arabam.com"
import os
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

def scraper_api_url(target_url: str) -> str:
    if SCRAPER_API_KEY:
        return f"https://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&country_code=tr"
    return target_url

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Referer": "https://www.arabam.com/",
    "Connection": "keep-alive",
}

BRAND_SLUGS = {
    "BMW": "bmw",
    "Mercedes": "mercedes-benz",
    "Audi": "audi",
    "Volkswagen": "volkswagen",
    "Toyota": "toyota",
    "Porsche": "porsche",
    "Volvo": "volvo",
    "Land Rover": "land-rover",
}


class ArabamLightScraper:

    def __init__(self):
        self.client = httpx.Client(
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def scrape_listings(self, filter: ScrapeFilter) -> list[CarListing]:
        from bs4 import BeautifulSoup
        all_listings = []
        max_pages = 1

        for page_num in range(1, max_pages + 1):
            url = self._build_url(filter, page_num)
            logger.info(f"[Arabam] Sayfa {page_num}: {url}")

            try:
                time.sleep(random.uniform(2, 4))
                api_url = scraper_api_url(url)
                resp = self.client.get(api_url)

                logger.info(f"Arabam HTTP {resp.status_code}, içerik uzunluğu: {len(resp.text)}")
                if resp.status_code == 403 or resp.status_code >= 400:
                    logger.warning(f"Arabam erişim engeli ({resp.status_code}) — duruyoruz")
                    logger.debug(f"İlk 500 karakter: {resp.text[:500]}")
                    break

                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                items = self._parse_page(soup, filter)

                if not items:
                    logger.info("Boş sayfa")
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
            brand_slug = BRAND_SLUGS.get(filter.brands[0], filter.brands[0].lower())
            path = f"ikinci-el/otomobil/{brand_slug}"

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

        # Arabam listing kartları
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

        # Link + başlık
        link_el = row.select_one("a[href*='/ilan/'], .listing-title a, td a")
        if not link_el:
            return None

        url = link_el.get("href", "")
        if url and not url.startswith("http"):
            url = f"{BASE_URL}{url}"

        title = link_el.get_text(strip=True)

        # ID URL'den çıkar
        if not listing_id:
            m = re.search(r"/ilan/(\d+)", url)
            listing_id = m.group(1) if m else url

        # Fiyat
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

        # Yıl ve KM — arabam'da genellikle ayrı span'larda
        attrs = [el.get_text(strip=True) for el in row.select("td, .listing-info span")]
        year = self._extract_year(attrs, title)
        km = self._extract_km(attrs)

        # Konum
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

    def _extract_year(self, attrs: list[str], title: str = "") -> int:
        for a in list(attrs) + [title]:
            m = re.search(r"\b(19|20)\d{2}\b", str(a))
            if m:
                return int(m.group())
        return 0

    def _extract_km(self, attrs: list[str]) -> int:
        for a in attrs:
            if "km" in a.lower():
                val = self._clean_int(a)
                if 0 < val < 2_000_000:
                    return val
        return 0

    def _extract_model(self, title: str, brand: str) -> str:
        if brand and title.startswith(brand):
            rest = title[len(brand):].strip().split()
            return rest[0] if rest else ""
        parts = title.split()
        return parts[1] if len(parts) > 1 else ""
