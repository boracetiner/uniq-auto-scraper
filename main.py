"""
Uniq Auto — Fırsat İlan Bulucu
Ana çalıştırma dosyası

Kullanım:
    python main.py                  # Scheduler başlat (her 15 dk)
    python main.py --once           # Tek seferlik çalıştır
    python main.py --test           # Test modu (1 sayfa, log verbose)
"""
import asyncio
import argparse
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

from db.database import Database
from models.listing import ScrapeFilter, Source
from scrapers.orchestrator import ScraperOrchestrator, DEFAULT_WATCH_FILTERS
from alerts.telegram_alert import TelegramAlert
from utils.price_engine import PriceEngine

load_dotenv()

# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///uniq_auto.db")  # SQLite fallback
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "15"))
MIN_SCORE = float(os.getenv("MIN_OPPORTUNITY_SCORE", "60"))


# ------------------------------------------------------------------ #
# Global instances
# ------------------------------------------------------------------ #
db = Database(DATABASE_URL)
price_engine = PriceEngine(db)
alert = TelegramAlert(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID) if TELEGRAM_TOKEN else None


# ------------------------------------------------------------------ #
# Ana iş mantığı
# ------------------------------------------------------------------ #

async def process_listing(listing):
    """Her ilan için: kaydet → fırsat hesapla → gerekirse alert at"""
    is_new = db.upsert_listing(listing)

    if not is_new:
        return  # Zaten bilinen ilan, sadece güncellendi

    # Fiyat motoru
    opportunity = price_engine.evaluate(listing)

    if opportunity is None:
        logger.debug(f"Karşılaştırma verisi yetersiz: {listing.title}")
        return

    log_msg = (
        f"[{listing.source}] {listing.title} | "
        f"{listing.price:,} TL | "
        f"Skor: {opportunity.opportunity_score:.0f} | "
        f"Piyasa: {opportunity.market_median:,.0f} TL"
    )

    if opportunity.opportunity_score >= MIN_SCORE:
        logger.success(f"🎯 FIRSAT: {log_msg}")
        if alert:
            await alert.send_opportunity(opportunity)
    else:
        logger.info(log_msg)


async def run_scrape_cycle():
    """Tek bir scrape döngüsü"""
    start = datetime.now()
    logger.info(f"═══ Scrape döngüsü başladı: {start.strftime('%H:%M:%S')} ═══")

    orchestrator = ScraperOrchestrator()

    try:
        listings = await orchestrator.run_all_filters(
            filters=DEFAULT_WATCH_FILTERS,
            on_listing=process_listing,
        )

        # Cross-source duplikat temizle
        unique = orchestrator.deduplicate_cross_source(listings)

        elapsed = (datetime.now() - start).seconds
        stats = db.stats()

        logger.info(
            f"═══ Döngü tamamlandı ({elapsed}s) | "
            f"Toplam aktif: {stats['active']:,} | "
            f"Bu döngü: {len(unique)} ═══"
        )

    except Exception as e:
        logger.error(f"Scrape döngüsü hatası: {e}")
        raise


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

async def main():
    parser = argparse.ArgumentParser(description="Uniq Auto Fırsat İlan Bulucu")
    parser.add_argument("--once", action="store_true", help="Tek seferlik çalıştır")
    parser.add_argument("--test", action="store_true", help="Test modu")
    parser.add_argument("--brand", type=str, help="Tek marka tara: 'BMW'")
    args = parser.parse_args()

    # Log seviyesi
    logger.remove()
    if args.test:
        logger.add(lambda msg: print(msg, end=""), level="DEBUG", colorize=True)
    else:
        logger.add("logs/scraper_{time:YYYY-MM-DD}.log", rotation="1 day", level="INFO")
        logger.add(lambda msg: print(msg, end=""), level="INFO", colorize=True)

    logger.info("🚗 Uniq Auto Fırsat Bulucu başlatıldı")

    if args.brand:
        # Tek marka modu
        custom_filter = ScrapeFilter(
            brands=[args.brand],
            price_min=500_000,
            price_max=3_000_000,
        )
        orchestrator = ScraperOrchestrator()
        await orchestrator.run_all_filters(
            filters=[custom_filter],
            on_listing=process_listing,
        )
        return

    if args.once or args.test:
        await run_scrape_cycle()
        return

    # Scheduler modu
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(
        run_scrape_cycle,
        "interval",
        minutes=SCRAPE_INTERVAL,
        next_run_time=datetime.now(),  # İlk çalışma hemen
        id="scrape_cycle",
        max_instances=1,  # Paralel çakışmayı önle
    )

    scheduler.start()
    logger.info(f"Scheduler başlatıldı — her {SCRAPE_INTERVAL} dakikada bir çalışacak")

    try:
        await asyncio.Event().wait()  # Sonsuza dek bekle
    except (KeyboardInterrupt, SystemExit):
        logger.info("Kapatılıyor...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
