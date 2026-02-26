"""
sahibinden.com otomobil scraper

Sahibinden JS-rendered site olduğu için Playwright zorunlu.
Sayfa yapısı değişirse güncellenecek selector'lar:
  - Liste: .searchResultsItem
  - Fiyat: .price-container span
  - Başlık: .classifiedTitle
  - Detay: çeşitli .classifiedInfoList li
"""
import re
from datetime import datetime
from typing import AsyncGenerator
from urllib.parse import urlencode, urljoin

from loguru import logger
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from models.listing import CarListing, ScrapeFilter, Source
from scrapers.base import BaseScraper


BASE_URL = "https://www.sahibinden.com"
LISTING_URL = f"{BASE_URL}/otomobil"

# sahibinden marka slug map — genişletilebilir
BRAND_SLUGS: dict[str, str] = {
    "BMW": "otomobil-bmw",
    "Mercedes": "otomobil-mercedes_benz",
    "Audi": "otomobil-audi",
    "Volkswagen": "otomobil-volkswagen",
    "Toyota": "otomobil-toyota",
    "Honda": "otomobil-honda",
    "Volvo": "otomobil-volvo",
    "Porsche": "otomobil-porsche",
    "Lexus": "otomobil-lexus",
    "Land Rover": "otomobil-land_rover",
}


class SahibindenScraper(BaseScraper):
    """
    sahibinden.com otomobil ilanı scraper.
    
    Kullanım:
        async with SahibindenScraper() as scraper:
            filter = ScrapeFilter(brands=["BMW"], price_min=1_500_000, price_max=3_000_000)
            async for listing in scraper.scrape_listings(filter):
                print(listing)
    """

    @property
    def source_name(self) -> str:
        return "sahibinden"

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #

    def _build_search_url(self, filter: ScrapeFilter, page: int = 0) -> str:
        """
        Filtre parametrelerini sahibinden URL'ine dönüştürür.
        sahibinden sayfalama: her sayfada 50 ilan, offset=page*50
        """
        params: dict = {
            "pagingOffset": page * 50,
            "pagingSize": 50,
            "sorting": "date_desc",  # En yeni önce
        }

        if filter.price_min:
            params["price_min"] = filter.price_min
        if filter.price_max:
            params["price_max"] = filter.price_max
        if filter.year_min:
            params["year_min"] = filter.year_min
        if filter.year_max:
            params["year_max"] = filter.year_max
        if filter.km_max:
            params["km_max"] = filter.km_max
        if filter.fuel_types:
            params["fuel_type"] = ",".join(filter.fuel_types)
        if filter.gear_types:
            params["gear"] = ",".join(filter.gear_types)

        # Marka/model filtresi varsa slug URL kullan
        if filter.brands and len(filter.brands) == 1:
            brand = filter.brands[0]
            slug = BRAND_SLUGS.get(brand, f"otomobil-{brand.lower()}")
            base = f"{BASE_URL}/{slug}"
        else:
            base = LISTING_URL

        return f"{base}?{urlencode(params)}"

    # ------------------------------------------------------------------ #
    # Ana scrape metodu
    # ------------------------------------------------------------------ #

    async def scrape_listings(
        self, filter: ScrapeFilter
    ) -> AsyncGenerator[CarListing, None]:
        """
        Tüm sayfalarda dolaşarak ilanları yield eder.
        Boş sayfa geldiğinde veya max_pages'e ulaşıldığında durur.
        """
        max_pages = 10  # Güvenlik: max 500 ilan / filtre
        page_num = 0

        async with self:
            page = await self._new_page()

            while page_num < max_pages:
                url = self._build_search_url(filter, page_num)
                logger.info(f"[Sahibinden] Sayfa {page_num + 1} çekiliyor: {url}")

                try:
                    await self._goto_with_retry(page, url)
                    await self._human_scroll(page)
                    await self._random_delay()

                    # CAPTCHA kontrolü
                    if await self._is_captcha(page):
                        logger.error("CAPTCHA tespit edildi! Bekleniyor...")
                        await self._handle_captcha(page)
                        continue

                    items = await self._parse_listing_page(page)

                    if not items:
                        logger.info(f"Sayfa {page_num + 1} boş — durduruluyor")
                        break

                    for item in items:
                        # Segment filtresi — sadece istenen fiyat aralığını yield et
                        if self._in_price_range(item.price, filter):
                            yield item

                    logger.success(f"Sayfa {page_num + 1}: {len(items)} ilan çekildi")
                    page_num += 1

                    # Sayfalar arası daha uzun bekleme
                    await self._random_delay(factor=1.5)

                except PlaywrightTimeout:
                    logger.warning(f"Timeout — sayfa {page_num + 1} atlanıyor")
                    page_num += 1
                except Exception as e:
                    logger.error(f"Scrape hatası: {e}")
                    break

    # ------------------------------------------------------------------ #
    # Sayfa parser
    # ------------------------------------------------------------------ #

    async def _parse_listing_page(self, page: Page) -> list[CarListing]:
        """Liste sayfasındaki tüm ilanları parse eder"""
        try:
            await page.wait_for_selector(".searchResultsItem", timeout=10_000)
        except PlaywrightTimeout:
            logger.warning("İlan listesi bulunamadı")
            return []

        raw_items = await page.evaluate("""
            () => {
                const items = [];
                document.querySelectorAll('.searchResultsItem').forEach(el => {
                    try {
                        // ID
                        const id = el.dataset.id || el.getAttribute('data-id') || '';

                        // URL
                        const linkEl = el.querySelector('a.classifiedTitle, a[href*="/ilan/"]');
                        const url = linkEl ? linkEl.href : '';

                        // Başlık
                        const title = linkEl ? linkEl.innerText.trim() : '';

                        // Fiyat — binlik ayırıcı TL sembolü temizlenir
                        const priceEl = el.querySelector('.price-container span, .classified-price');
                        const priceRaw = priceEl ? priceEl.innerText : '0';

                        // Özellikler (yıl, km, renk vs.)
                        const props = {};
                        el.querySelectorAll('.searchResultsAttributeValue').forEach((td, i) => {
                            props['attr_' + i] = td.innerText.trim();
                        });

                        // Konum
                        const locEl = el.querySelector('.searchResultsLocationValue, .classified-location');
                        const location = locEl ? locEl.innerText.trim() : '';

                        // Tarih
                        const dateEl = el.querySelector('.searchResultsDateValue, .classified-date');
                        const dateRaw = dateEl ? dateEl.innerText.trim() : '';

                        // Satıcı tipi (galeri mi, bireysel mi)
                        const sellerEl = el.querySelector('.classified-type, .seller-type');
                        const sellerType = sellerEl ? sellerEl.innerText.trim() : '';

                        items.push({
                            id, url, title, priceRaw, location, dateRaw, sellerType,
                            attr0: props.attr_0 || '',  // Yıl
                            attr1: props.attr_1 || '',  // KM
                            attr2: props.attr_2 || '',  // Renk
                            attr3: props.attr_3 || '',  // Yakıt
                            attr4: props.attr_4 || '',  // Vites
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
        """Ham JS çıktısını CarListing modeline dönüştürür"""
        try:
            if not raw.get("id") or not raw.get("url"):
                return None

            # Başlıktan marka/model çıkar: "BMW 3 Serisi 320i"
            brand, model, series = self._parse_title(raw.get("title", ""))

            # Fiyat temizle: "1.850.000 TL" → 1850000
            price = self._clean_price(raw.get("priceRaw", "0"))
            if price == 0:
                return None

            # Yıl
            year = self._clean_int(raw.get("attr0", "0"))

            # KM: "45.000 km" → 45000
            km = self._clean_int(raw.get("attr1", "0"))

            return CarListing(
                id=f"sahibinden_{raw['id']}",
                source=Source.SAHIBINDEN,
                url=raw["url"] if raw["url"].startswith("http") else f"{BASE_URL}{raw['url']}",
                title=raw.get("title", ""),
                brand=brand,
                model=model,
                series=series,
                year=year,
                km=km,
                price=price,
                color=raw.get("attr2") or None,
                fuel_type=raw.get("attr3") or None,
                gear_type=raw.get("attr4") or None,
                location=raw.get("location", ""),
                seller_type=raw.get("sellerType") or None,
                listed_at=self._parse_date(raw.get("dateRaw", "")),
                scraped_at=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Mapping hatası: {e} | raw: {raw}")
            return None

    # ------------------------------------------------------------------ #
    # Detay sayfası scraper
    # ------------------------------------------------------------------ #

    async def scrape_detail(self, url: str) -> CarListing | None:
        """
        Tek ilan detay sayfasını çeker.
        Liste sayfasında olmayan veriler buradan gelir:
        - Motor hacmi, beygir gücü, hasar kaydı, boya durumu, vb.
        """
        async with self:
            page = await self._new_page()
            try:
                await self._goto_with_retry(page, url)
                await self._random_delay()

                detail = await page.evaluate("""
                    () => {
                        const info = {};
                        
                        // Tüm özellik satırlarını çek
                        document.querySelectorAll('.classifiedInfoList li').forEach(li => {
                            const label = li.querySelector('.classifiedInfoItemLabel')?.innerText?.trim();
                            const value = li.querySelector('.classifiedInfoItemValue')?.innerText?.trim();
                            if (label && value) info[label] = value;
                        });

                        // Fiyat
                        info['_price'] = document.querySelector('.classified-price-wrapper strong')?.innerText || '';
                        
                        // Açıklama
                        info['_description'] = document.querySelector('#classifiedDescription')?.innerText?.trim() || '';
                        
                        // Tüm görseller
                        info['_images'] = Array.from(
                            document.querySelectorAll('.classified-main-img img, .photos img')
                        ).map(img => img.src).filter(Boolean);

                        // Satıcı ID
                        info['_sellerId'] = document.querySelector('[data-store-id]')?.dataset?.storeId || '';

                        return info;
                    }
                """)

                # Ham detaydan listing oluştur
                return self._map_detail_to_listing(url, detail)

            except Exception as e:
                logger.error(f"Detay çekilemedi ({url}): {e}")
                return None

    def _map_detail_to_listing(self, url: str, detail: dict) -> CarListing | None:
        """Detay sayfası verisini CarListing'e map'ler"""
        try:
            # ID URL'den çıkar
            id_match = re.search(r"/ilan/(\d+)", url)
            listing_id = id_match.group(1) if id_match else url

            title = detail.get("Başlık", detail.get("İlan Başlığı", ""))
            brand, model, series = self._parse_title(title)

            return CarListing(
                id=f"sahibinden_{listing_id}",
                source=Source.SAHIBINDEN,
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
                location=detail.get("Şehir", ""),
                seller_id=detail.get("_sellerId"),
                images=detail.get("_images", []),
                scraped_at=datetime.now(),
            )
        except Exception as e:
            logger.error(f"Detay map hatası: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Anti-bot yönetimi
    # ------------------------------------------------------------------ #

    async def _is_captcha(self, page: Page) -> bool:
        """Sahibinden'in captcha/blocked sayfasını tespit et"""
        try:
            content = await page.content()
            captcha_signals = [
                "captcha",
                "robot değil",
                "doğrulama",
                "erişim engellendi",
                "cf-challenge",
                "recaptcha",
            ]
            return any(sig in content.lower() for sig in captcha_signals)
        except:
            return False

    async def _handle_captcha(self, page: Page):
        """
        CAPTCHA tespit edildiğinde yapılacaklar:
        1. Yeni context aç (yeni IP olmaz ama cookie temizlenir)
        2. Uzun bekleme
        3. TODO: 2captcha / anti-captcha servisi entegre edilebilir
        """
        logger.warning("CAPTCHA — yeni context açılıyor, 60s bekleniyor")
        await self._new_context()
        await self._random_delay(factor=15)

    # ------------------------------------------------------------------ #
    # Yardımcı parser'lar
    # ------------------------------------------------------------------ #

    def _parse_title(self, title: str) -> tuple[str, str, str | None]:
        """
        "BMW 3 Serisi 320i" → ("BMW", "3 Serisi", "320i")
        "Volkswagen Passat 1.6 TDI" → ("Volkswagen", "Passat", "1.6 TDI")
        """
        known_brands = list(BRAND_SLUGS.keys()) + [
            "Renault", "Peugeot", "Fiat", "Ford", "Hyundai",
            "Kia", "Nissan", "Mazda", "Subaru", "Jeep",
        ]
        parts = title.strip().split()

        brand = ""
        model = ""
        series = None

        for i, known in enumerate(known_brands):
            if title.startswith(known):
                brand = known
                remaining = title[len(known):].strip()
                tokens = remaining.split()
                if tokens:
                    model = tokens[0]
                    if len(tokens) > 1:
                        series = " ".join(tokens[1:])
                break

        if not brand and parts:
            brand = parts[0]
            model = parts[1] if len(parts) > 1 else ""
            series = " ".join(parts[2:]) if len(parts) > 2 else None

        return brand, model, series

    def _clean_price(self, raw: str) -> int:
        """'1.850.000 TL' veya '1,850,000' → 1850000"""
        digits = re.sub(r"[^\d]", "", raw)
        return int(digits) if digits else 0

    def _clean_int(self, raw: str) -> int:
        """'45.000 km' veya '45000' → 45000"""
        digits = re.sub(r"[^\d]", "", raw)
        return int(digits) if digits else 0

    def _parse_date(self, raw: str) -> datetime | None:
        """
        Sahibinden tarih formatları:
        - "20 Mayıs 2024"
        - "2 saat önce"
        - "Bugün 14:30"
        """
        if not raw:
            return None

        tr_months = {
            "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4,
            "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
            "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
        }

        raw_lower = raw.lower()

        if "saat önce" in raw_lower or "bugün" in raw_lower:
            return datetime.now()
        if "dün" in raw_lower:
            from datetime import timedelta
            return datetime.now() - timedelta(days=1)

        for month_name, month_num in tr_months.items():
            if month_name in raw_lower:
                match = re.search(r"(\d{1,2})\s+\w+\s+(\d{4})", raw)
                if match:
                    try:
                        return datetime(int(match.group(2)), month_num, int(match.group(1)))
                    except:
                        pass
        return None

    def _in_price_range(self, price: int, filter: ScrapeFilter) -> bool:
        if filter.price_min and price < filter.price_min:
            return False
        if filter.price_max and price > filter.price_max:
            return False
        return True
