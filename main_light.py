"""
main_light.py — GitHub Actions için

Playwright gerektirmez, httpx + BeautifulSoup kullanır.
Her çalışmada:
  1. sahibinden + arabam'ı tara
  2. Yeni ilanları veritabanına kaydet
  3. Fırsat skoru hesapla
  4. Eşiği geçenleri Telegram'a at
"""
import os
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///uniq_auto.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
MIN_SCORE = float(os.environ.get("MIN_OPPORTUNITY_SCORE", "60"))

# Supabase bağlantısı postgresql:// formatında gelir,
# SQLAlchemy için postgresql+psycopg2:// olmalı
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

from db.database import Database
from utils.price_engine import PriceEngine
from alerts.telegram_alert import TelegramAlert
from scrapers.sahibinden_light import SahibindenLightScraper
from scrapers.arabam_light import ArabamLightScraper
from scrapers.orchestrator import DEFAULT_WATCH_FILTERS


def send_telegram_sync(token: str, chat_id: str, text: str):
    """Sync Telegram mesajı — async bot olmadan"""
    import httpx
    if not token or not chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Telegram gönderim hatası: {e}")


def format_opportunity_message(listing, opp) -> str:
    score = opp.opportunity_score
    if score >= 80:
        emoji = "🔥🔥🔥"
    elif score >= 65:
        emoji = "🔥🔥"
    else:
        emoji = "🔥"

    return (
        f"{emoji} *FIRSAT İLAN* — Skor: {score:.0f}/100\n\n"
        f"🚗 {listing.title}\n"
        f"📅 {listing.year} | 🛣️ {listing.km:,} km\n\n"
        f"💰 *İlan Fiyatı:* {listing.price:,} TL\n"
        f"📊 Piyasa Ortalaması: {opp.market_median:,.0f} TL\n"
        f"✅ Tasarruf: *{opp.discount_amount:,.0f} TL* (%{opp.discount_pct:.1f})\n\n"
        f"📍 {listing.location} | 🏷️ {listing.source}\n"
        f"🔗 [İlana Git]({listing.url})"
    )


def main():
    start = datetime.now()
    logger.info(f"🚗 Uniq Auto tarama başladı — {start.strftime('%H:%M:%S')}")

    # Bağlantılar
    db = Database(DATABASE_URL)
    price_engine = PriceEngine(db)

    new_count = 0
    opportunity_count = 0
    total_scraped = 0

    # Her filtre için her iki siteyi çalıştır
    for i, filter in enumerate(DEFAULT_WATCH_FILTERS):
        brand_label = ", ".join(filter.brands) if filter.brands else "Tümü"
        logger.info(
            f"Filtre {i+1}/{len(DEFAULT_WATCH_FILTERS)}: "
            f"{brand_label} | {filter.price_min:,}-{filter.price_max:,} TL"
        )

        # Sahibinden
        with SahibindenLightScraper() as scraper:
            s_listings = scraper.scrape_listings(filter)

        # Arabam
        with ArabamLightScraper() as scraper:
            a_listings = scraper.scrape_listings(filter)

        all_listings = s_listings + a_listings
        total_scraped += len(all_listings)

        # Kaydet ve değerlendir
        seen_ids = set()
        for listing in all_listings:
            # Bu döngüde zaten gördük mü?
            if listing.id in seen_ids:
                continue
            seen_ids.add(listing.id)

            is_new = db.upsert_listing(listing)

            if not is_new:
                continue  # Zaten bilinen ilan

            new_count += 1

            # Fiyat motoru
            opp = price_engine.evaluate(listing)
            if opp is None:
                logger.debug(f"Karşılaştırma verisi yok: {listing.title}")
                continue

            logger.info(
                f"[{listing.source}] {listing.title} | "
                f"{listing.price:,} TL | Skor: {opp.opportunity_score:.0f}"
            )

            if opp.opportunity_score >= MIN_SCORE:
                opportunity_count += 1
                msg = format_opportunity_message(listing, opp)
                send_telegram_sync(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
                logger.success(f"🎯 FIRSAT: {listing.title}")

    # Özet
    elapsed = (datetime.now() - start).seconds
    stats = db.stats()
    summary = (
        f"✅ Tarama tamamlandı ({elapsed}s)\n"
        f"📦 Çekilen: {total_scraped} | Yeni: {new_count} | "
        f"Fırsat: {opportunity_count} | DB toplam: {stats['active']:,}"
    )
    logger.success(summary)

    # Günlük ilk çalışmada özet gönder (saat 09:00 UTC = 12:00 TR)
    current_hour = datetime.utcnow().hour
    if current_hour == 9 and datetime.utcnow().minute < 30:
        send_telegram_sync(
            TELEGRAM_TOKEN,
            TELEGRAM_CHAT_ID,
            f"📈 *Günlük Özet — Uniq Auto*\n\n{summary}\n\nSahibinden: {stats['by_source'].get('sahibinden', 0)}\nArabam: {stats['by_source'].get('arabam', 0)}"
        )


if __name__ == "__main__":
    main()
