import asyncio
import random
from abc import ABC, abstractmethod
from typing import AsyncGenerator

from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_exponential

from models.listing import CarListing, ScrapeFilter


# Gerçekçi User-Agent listesi
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Gerçek viewport boyutları
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]


class BaseScraper(ABC):
    """
    Tüm site scraper'larının miras aldığı temel sınıf.
    Anti-detection, retry, rate limiting burada yönetilir.
    """

    def __init__(
        self,
        headless: bool = True,
        delay_min: float = 2.0,
        delay_max: float = 5.0,
    ):
        self.headless = headless
        self.delay_min = delay_min
        self.delay_max = delay_max
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ------------------------------------------------------------------ #
    # Browser yönetimi
    # ------------------------------------------------------------------ #

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        await self._new_context()
        return self

    async def __aexit__(self, *args):
        await self._browser.close()
        await self._playwright.stop()

    async def _new_context(self):
        """Her session'da taze context — cookie izolasyonu"""
        if self._context:
            await self._context.close()

        ua = random.choice(USER_AGENTS)
        vp = random.choice(VIEWPORTS)

        self._context = await self._browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            # WebRTC leak önleme
            permissions=[],
        )

        # navigator.webdriver'ı gizle
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['tr-TR','tr','en-US']});
            window.chrome = {runtime: {}};
        """)

    async def _new_page(self) -> Page:
        page = await self._context.new_page()

        # Gereksiz kaynakları blokla — hız için
        await page.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,mp4,mp3}",
            lambda r: r.abort()
            if r.request.resource_type in ("image", "media", "font")
            else r.continue_(),
        )
        return page

    # ------------------------------------------------------------------ #
    # Yardımcı metodlar
    # ------------------------------------------------------------------ #

    async def _random_delay(self, factor: float = 1.0):
        """İnsan gibi bekleme — bot tespitini zorlaştırır"""
        delay = random.uniform(self.delay_min * factor, self.delay_max * factor)
        logger.debug(f"Bekleniyor: {delay:.1f}s")
        await asyncio.sleep(delay)

    async def _human_scroll(self, page: Page):
        """Rastgele scroll hareketi"""
        for _ in range(random.randint(2, 4)):
            scroll_y = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_y})")
            await asyncio.sleep(random.uniform(0.3, 0.8))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        reraise=True,
    )
    async def _goto_with_retry(self, page: Page, url: str):
        """Timeout ve hata durumunda otomatik retry"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            logger.warning(f"Sayfa yüklenemedi ({url}): {e} — yeniden deneniyor")
            raise

    # ------------------------------------------------------------------ #
    # Alt sınıfların implement etmesi gereken metodlar
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def scrape_listings(
        self, filter: ScrapeFilter
    ) -> AsyncGenerator[CarListing, None]:
        """
        Filtre parametrelerine göre ilanları yield eder.
        Generator yapısı sayesinde bellek dostu — liste beklemiyor.
        """
        ...

    @abstractmethod
    async def scrape_detail(self, url: str) -> CarListing | None:
        """Tek bir ilan detay sayfasını çeker"""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...
