"""
arabam.com otomobil scraper

arabam.com API tabanlı — bazı endpoint'leri JSON döndürür,
bu da sahibinden'e kıyasla daha stabil bir scraping sağlar.
"""
import re
from datetime import datetime
from typing import AsyncGenerator
from urllib.parse import urlencode

from loguru import logger
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from models.listing import CarListing, ScrapeFilter, Source
from scrapers.base import BaseScraper


BASE_URL = "https://www.arabam.com"
LISTING_URL = f"{BASE_URL}/ikinci-el/otomobil"

# arabam.com marka slug'ları
BRAND_SLUGS: dict[str, str] = {
    "BMW": "bmw",
    "Mercedes": "mercedes-benz",
    "Audi": "audi",
    "Volkswagen": "volkswagen",
    "Toyota": "toyota",
    "Honda": "honda",
    "Volvo": "volvo",
    "Porsche": "porsche",
    "Lexus": "lexus",
    "Land Rover": "land-rover",
}

# arabam sıralama parametreleri
SORT_OPTIONS = {
    "newest": "0",        # En yeni
    "price_asc": "1",     # Fiyat artan
    "price_desc": "2",    # Fiyat azalan
    "km_asc": "3",        # KM artan
}


class ArabamScraper(BaseScraper):
    """
    arabam.com otomobil ilanı scraper.

    Kullanım:
        async with ArabamScraper() as scraper:
            filter = ScrapeFilter(brands=["BMW"], price_min=1_500_000, price_max=3_000_000)
            async for listing in scraper.scrape_listings(filter):
                print(listing)
    """

    @property
    def source_name(self) -> str:
        return "arabam"

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #

    def _build_search_url(self, filter: ScrapeFilter, page: int = 1) -> str:
        """
        arabam.com sayfalama: ?page=1, ?page=2, ...
        Her sayfada ~20 ilan
        """
        # Marka + model slug oluştur
        path_parts = ["ikinci-el", "otomobil"]

        if filter.brands and len(filter.brands) == 1:
            brand_slug = BRAND_SLUGS.get(filter.brands[0], filter.brands[0].lower())
            path_parts.append(brand_slug)

            if filter.models and len(filter.models) == 1:
                path_parts.append(filter.models[0].lower().replace(" ", "-"))

        base_path = "/".join(path_parts)

        params: dict = {
            "page": page,
            "sort": SORT_OPTIONS["newest"],
            "take": 50,
        }

        if filter.price_min:
            params["minPrice"] = filter.price_min
        if filter.price_max:
            params["maxPrice"] = filter.price_max
        if filter.year_min:
            params["minYear"] = filter.year_min
        if filter.year_max:
            params["maxYear"] = filter.year_max
        if filter.km_max:
            params["maxKm"] = filter.km_max

        return f"{BASE_URL}/{base_path}?{urlencode(params)}"

    # ------------------------------------------------------------------ #
    # Ana scrape metodu
    # ------------------------------------------------------------------ #

    async def scrape_listings(
        self, filter: ScrapeFilter
    ) -> AsyncGenerator[CarListing, None]:
        max_pages = 10
        page_num = 1

        async with self:
            page = await self._new_page()

            while page_num <= max_pages:
                url = self._build_search_url(filter, page_num)
                logger.info(f"[Arabam] Sayfa {page_num} çekiliyor: {url}")

                try:
                    await self._goto_with_retry(page, url)
                    await self._human_scroll(page)
                    await self._random_delay()

                    # arabam'da bot engeli tespiti
                    if await self._is_blocked(page):
                        logger.warning("Arabam erişim engeli — bekleniyor")
                        await self._new_context()
                        page = await self._new_page()
                        await self._random_delay(factor=10)
                        continue

                    items = await self._parse_listing_page(page)

                    if not items:
                        logger.info(f"Sayfa {page_num} boş — durduruluyor")
                        break

                    for item in items:
                        if self._in_price_range(item.price, filter):
                            yield item

                    logger.success(f"Sayfa {page_num}: {len(items)} ilan")
                    page_num += 1
                    await self._random_delay(factor=1.5)

                except PlaywrightTimeout:
                    logger.warning(f"Timeout — sayfa {page_num} atlanıyor")
                    page_num += 1
                except Exception as e:
                    logger.error(f"Scrape hatası: {e}")
                    break

    # ------------------------------------------------------------------ #
    # Sayfa parser
    # ------------------------------------------------------------------ #

    async def _parse_listing_page(self, page: Page) -> list[CarListing]:
        """arabam.com liste sayfası parser"""
        try:
            # arabam ilan kartları için bekle
            await page.wait_for_selector(
                "[data-listing-id], .listing-list-item, .listing-item",
                timeout=10_000
            )
        except PlaywrightTimeout:
            logger.warning("arabam ilan listesi bulunamadı")
            return []

        raw_items = await page.evaluate("""
            () => {
                const items = [];
                
                // arabam.com DOM yapısı — birden fazla selector dene
                const selectors = [
                    '[data-listing-id]',
                    '.listing-list-item',
                    'tr.listing-item',
                ];
                
                let listEl = null;
                for (const sel of selectors) {
                    const found = document.querySelectorAll(sel);
                    if (found.length > 0) { listEl = found; break; }
                }
                
                if (!listEl) return [];
                
                listEl.forEach(el => {
                    try {
                        const id = el.dataset.listingId || el.dataset.id || '';
                        
                        // Link
                        const linkEl = el.querySelector('a[href*="/ilan/"]') 
                            || el.querySelector('.listing-title a')
                            || el.querySelector('a');
                        const url = linkEl ? linkEl.href : '';
                        const title = linkEl ? linkEl.innerText.trim() : 
                                      el.querySelector('.listing-title')?.innerText?.trim() || '';
                        
                        // Fiyat
                        const priceEl = el.querySelector('.listing-price, [data-price], .price');
                        const priceRaw = priceEl ? 
                            (priceEl.dataset.price || priceEl.innerText) : '0';
                        
                        // Attributes: yıl, km
                        const attrs = el.querySelectorAll('.listing-modelname-and-key-info span, td');
                        const attrTexts = Array.from(attrs).map(a => a.innerText.trim()).filter(Boolean);
                        
                        // Konum
                        const locEl = el.querySelector('.listing-location, [class*="location"]');
                        const location = locEl ? locEl.innerText.trim() : '';
                        
                        // Tarih
                        const dateEl = el.querySelector('.listing-date, [class*="date"]');
                        const dateRaw = dateEl ? dateEl.innerText.trim() : '';

                        // Görsel
                        const imgEl = el.querySelector('img[src*="arabam"], img.listing-img');
                        const imgSrc = imgEl ? imgEl.src : '';

                        items.push({
                            id, url, title, priceRaw, location, dateRaw,
                            attrs: attrTexts,
                            imgSrc,
                        });
                    } catch(e) {}
                });
                
                return items;
            }
        """)

        listings = []
        for raw in raw_items:
            listing = self._map_to_listing(raw)
            if listing:
                listings.append(listing)
        return listings

    def _map_to_listing(self, raw: dict) -> CarListing | None:
        try:
            if not raw.get("url"):
                return None

            # ID
            listing_id = raw.get("id") or re.search(r"/ilan/(\d+)", raw["url"])
            if hasattr(listing_id, "group"):
                listing_id = listing_id.group(1)

            title = raw.get("title", "")
            brand, model, series = self._parse_title(title)
            price = self._clean_price(raw.get("priceRaw", "0"))

            if price == 0:
                return None

            # arabam attr sırası genellikle: [yıl, km, renk, yakıt, vites]
            attrs = raw.get("attrs", [])
            year = self._extract_year(attrs)
            km = self._extract_km(attrs)

            images = [raw["imgSrc"]] if raw.get("imgSrc") else []

            return CarListing(
                id=f"arabam_{listing_id}",
                source=Source.ARABAM,
                url=raw["url"] if raw["url"].startswith("http") else f"{BASE_URL}{raw['url']}",
                title=title,
                brand=brand,
                model=model,
                series=series,
                year=year,
                km=km,
                price=price,
                location=raw.get("location", ""),
                images=images,
                listed_at=self._parse_date(raw.get("dateRaw", "")),
                scraped_at=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"arabam map hatası: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Detay sayfası
    # ------------------------------------------------------------------ #

    async def scrape_detail(self, url: str) -> CarListing | None:
        async with self:
            page = await self._new_page()
            try:
                await self._goto_with_retry(page, url)
                await self._random_delay()

                detail = await page.evaluate("""
                    () => {
                        const info = {};
                        
                        // arabam özellik tablosu
                        document.querySelectorAll('.listing-properties tr, .spec-list li').forEach(row => {
                            const cells = row.querySelectorAll('th, td, span');
                            if (cells.length >= 2) {
                                info[cells[0].innerText.trim()] = cells[1].innerText.trim();
                            }
                        });

                        info['_price'] = document.querySelector(
                            'span[data-price], .listing-price strong, h3.price'
                        )?.innerText || '';
                        
                        info['_title'] = document.querySelector(
                            'h1.listing-title, h1'
                        )?.innerText?.trim() || '';

                        info['_images'] = Array.from(
                            document.querySelectorAll('.gallery img, .photo-slider img')
                        ).map(img => img.src || img.dataset.src).filter(Boolean);

                        info['_location'] = document.querySelector(
                            '.listing-location, [class*="location"] span'
                        )?.innerText?.trim() || '';

                        return info;
                    }
                """)

                return self._map_detail_to_listing(url, detail)

            except Exception as e:
                logger.error(f"arabam detay hatası ({url}): {e}")
                return None

    def _map_detail_to_listing(self, url: str, detail: dict) -> CarListing | None:
        try:
            id_match = re.search(r"/ilan/(\d+)", url)
            listing_id = id_match.group(1) if id_match else url

            title = detail.get("_title", "")
            brand, model, series = self._parse_title(title)

            return CarListing(
                id=f"arabam_{listing_id}",
                source=Source.ARABAM,
                url=url,
                title=title,
                brand=brand,
                model=model,
                series=series,
                year=self._clean_int(detail.get("Yıl", "0")),
                km=self._clean_int(detail.get("Kilometre", "0")),
                price=self._clean_price(detail.get("_price", "0")),
                color=detail.get("Renk"),
                fuel_type=detail.get("Yakıt Tipi"),
                gear_type=detail.get("Vites Tipi"),
                body_type=detail.get("Kasa Tipi"),
                location=detail.get("_location", ""),
                images=detail.get("_images", []),
                scraped_at=datetime.now(),
            )
        except Exception as e:
            logger.error(f"arabam detay map hatası: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Yardımcılar
    # ------------------------------------------------------------------ #

    async def _is_blocked(self, page: Page) -> bool:
        try:
            content = await page.content()
            return any(s in content.lower() for s in [
                "erişim engel", "blocked", "cloudflare", "captcha"
            ])
        except:
            return False

    def _parse_title(self, title: str) -> tuple[str, str, str | None]:
        known_brands = list(BRAND_SLUGS.keys()) + [
            "Renault", "Peugeot", "Fiat", "Ford", "Hyundai",
            "Kia", "Nissan", "Mazda", "Subaru", "Jeep", "Skoda",
        ]
        parts = title.strip().split()
        brand, model, series = "", "", None

        for known in known_brands:
            if title.startswith(known):
                brand = known
                remaining = title[len(known):].strip().split()
                model = remaining[0] if remaining else ""
                series = " ".join(remaining[1:]) if len(remaining) > 1 else None
                break

        if not brand and parts:
            brand = parts[0]
            model = parts[1] if len(parts) > 1 else ""
            series = " ".join(parts[2:]) if len(parts) > 2 else None

        return brand, model, series

    def _clean_price(self, raw: str) -> int:
        if isinstance(raw, (int, float)):
            return int(raw)
        digits = re.sub(r"[^\d]", "", str(raw))
        return int(digits) if digits else 0

    def _clean_int(self, raw: str) -> int:
        digits = re.sub(r"[^\d]", "", str(raw))
        return int(digits) if digits else 0

    def _extract_year(self, attrs: list[str]) -> int:
        for attr in attrs:
            match = re.search(r"\b(19|20)\d{2}\b", attr)
            if match:
                return int(match.group())
        return 0

    def _extract_km(self, attrs: list[str]) -> int:
        for attr in attrs:
            if "km" in attr.lower():
                return self._clean_int(attr)
        return 0

    def _parse_date(self, raw: str) -> datetime | None:
        if not raw:
            return None
        if "saat" in raw or "dakika" in raw or "bugün" in raw.lower():
            return datetime.now()
        from datetime import timedelta
        if "dün" in raw.lower():
            return datetime.now() - timedelta(days=1)
        return None

    def _in_price_range(self, price: int, filter: ScrapeFilter) -> bool:
        if filter.price_min and price < filter.price_min:
            return False
        if filter.price_max and price > filter.price_max:
            return False
        return True
