"""
Sahibinden hafif scraper — Playwright olmadan çalışır.

Sahibinden'in arama sonuçlarını döndüren JSON endpoint'ini kullanır.
Bu endpoint browser olmadan httpx ile çağrılabilir.
"""
import re
import time
import random
import httpx
from datetime import datetime
from loguru import logger
from models.listing import CarListing, ScrapeFilter, Source


BASE_URL = "https://www.sahibinden.com"

# Sahibinden kategori ID'leri (otomobil alt kategorileri)
CATEGORY_IDS = {
    "BMW": "3",
    "Mercedes": "9",
    "Audi": "2",
    "Volkswagen": "18",
    "Toyota": "16",
    "Honda": "6",
    "Volvo": "19",
    "Porsche": "13",
    "Lexus": "8",
    "Land Rover": "7",
    "default": ""   # Tümü
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.sahibinden.com/",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


class SahibindenLightScraper:
    """
    Playwright gerektirmeyen hafif scraper.
    httpx ile HTML çekip BeautifulSoup ile parse eder.
    """

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
        """Tüm sayfaları tara, ilanları döndür"""
        from bs4 import BeautifulSoup
        all_listings = []
        max_pages = 5  # GitHub Actions'da fazla sürmemesi için

        for page_num in range(max_pages):
            url = self._build_url(filter, page_num)
            logger.info(f"[Sahibinden] Sayfa {page_num + 1}: {url}")

            try:
                # İnsan gibi rastgele bekleme
                time.sleep(random.uniform(2, 4))

                resp = self.client.get(url)

                if resp.status_code == 403:
                    logger.warning("Sahibinden erişim engeli (403) — duruyoruz")
                    break

                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code} — atlanıyor")
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Bot sayfasına düştük mü?
                if self._is_blocked(soup):
                    logger.warning("Bot engeli tespit edildi — duruyoruz")
                    break

                items = self._parse_page(soup, filter)

                if not items:
                    logger.info("Boş sayfa — tamamlandı")
                    break

                all_listings.extend(items)
                logger.success(f"Sayfa {page_num + 1}: {len(items)} ilan")

                # Son sayfaysa dur
                if len(items) < 20:
                    break

            except httpx.TimeoutException:
                logger.warning(f"Timeout — sayfa {page_num + 1} atlandı")
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

        # Marka slug
        if filter.brands:
            brand = filter.brands[0]
            slug_map = {
                "BMW": "otomobil-bmw",
                "Mercedes": "otomobil-mercedes_benz",
                "Audi": "otomobil-audi",
                "Volkswagen": "otomobil-volkswagen",
                "Porsche": "otomobil-porsche",
                "Volvo": "otomobil-volvo",
            }
            slug = slug_map.get(brand, "otomobil")
            return f"{BASE_URL}/{slug}?{query}"

        return f"{BASE_URL}/otomobil?{query}"

    def _parse_page(self, soup, filter: ScrapeFilter) -> list[CarListing]:
        from bs4 import Tag
        listings = []

        rows = soup.select("tr.searchResultsItem")
        if not rows:
            # Alternatif selector
            rows = soup.select(".classified-list li")

        for row in rows:
            try:
                listing = self._parse_row(row, filter)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Row parse hatası: {e}")

        return listings

    def _parse_row(self, row, filter: ScrapeFilter) -> CarListing | None:
        # ID
        listing_id = row.get("data-id", "")
        if not listing_id:
            return None

        # Başlık + URL
        title_el = row.select_one("a.classifiedTitle")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        url = title_el.get("href", "")
        if url and not url.startswith("http"):
            url = f"{BASE_URL}{url}"

        # Fiyat
        price_el = row.select_one(".price-container span, .classified-price")
        price = self._clean_int(price_el.get_text() if price_el else "0")
        if price == 0:
            return None

        # Filtre kontrolü
        if filter.price_min and price < filter.price_min:
            return None
        if filter.price_max and price > filter.price_max:
            return None

        # Özellikler (yıl, km, renk vs.)
        attrs = [el.get_text(strip=True) for el in row.select(".searchResultsAttributeValue")]

        year = self._extract_year(attrs)
        km = self._extract_km(attrs)
        color = attrs[2] if len(attrs) > 2 else None
        fuel_type = attrs[3] if len(attrs) > 3 else None
        gear_type = attrs[4] if len(attrs) > 4 else None

        # Konum
        loc_el = row.select_one(".searchResultsLocationValue")
        location = loc_el.get_text(strip=True) if loc_el else ""

        # Tarih
        date_el = row.select_one(".searchResultsDateValue")
        date_raw = date_el.get_text(strip=True) if date_el else ""

        # Marka/model
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
            listed_at=self._parse_date(date_raw),
            scraped_at=datetime.now(),
        )

    def _is_blocked(self, soup) -> bool:
        text = soup.get_text().lower()
        return any(s in text for s in ["captcha", "robot değil", "erişim engellendi"])

    def _clean_int(self, raw: str) -> int:
        digits = re.sub(r"[^\d]", "", str(raw))
        return int(digits) if digits else 0

    def _extract_year(self, attrs: list[str]) -> int:
        for a in attrs:
            m = re.search(r"\b(19|20)\d{2}\b", a)
            if m:
                return int(m.group())
        return 0

    def _extract_km(self, attrs: list[str]) -> int:
        for a in attrs:
            if "km" in a.lower() or re.search(r"\d{3,}", a):
                val = self._clean_int(a)
                if 0 < val < 2_000_000:
                    return val
        return 0

    def _extract_model(self, title: str, brand: str) -> str:
        if brand and title.startswith(brand):
            rest = title[len(brand):].strip().split()
            return rest[0] if rest else ""
        return title.split()[1] if len(title.split()) > 1 else ""

    def _parse_date(self, raw: str) -> datetime | None:
        if not raw:
            return None
        if any(s in raw.lower() for s in ["bugün", "saat", "dakika"]):
            return datetime.now()
        return None
