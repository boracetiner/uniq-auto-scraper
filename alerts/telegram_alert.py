"""
Telegram Alert Sistemi

Fırsat ilanları Telegram'a anlık bildirim olarak gönderilir.
Bot oluşturma: @BotFather → /newbot
Chat ID alma: @userinfobot
"""
import asyncio
from loguru import logger

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot kurulu değil — alertler devre dışı")

from models.listing import OpportunityResult


CONFIDENCE_EMOJI = {
    "high": "🟢",
    "medium": "🟡",
    "low": "🔴",
}

SCORE_EMOJI = {
    (80, 100): "🔥🔥🔥",
    (65, 80): "🔥🔥",
    (50, 65): "🔥",
    (0, 50): "⚡",
}


def _score_emoji(score: float) -> str:
    for (low, high), emoji in SCORE_EMOJI.items():
        if low <= score <= high:
            return emoji
    return "⚡"


class TelegramAlert:

    def __init__(self, token: str, chat_id: str):
        self.chat_id = chat_id
        self._bot = Bot(token=token) if TELEGRAM_AVAILABLE and token else None

    async def send_opportunity(self, opp: OpportunityResult):
        if not self._bot:
            logger.debug(f"[ALERT SİMÜLASYONU] {opp.listing.title} — Skor: {opp.opportunity_score:.0f}")
            return

        listing = opp.listing
        score_emoji = _score_emoji(opp.opportunity_score)
        conf_emoji = CONFIDENCE_EMOJI.get(opp.confidence, "⚪")

        message = (
            f"{score_emoji} *FIRSAT İLAN* — Skor: {opp.opportunity_score:.0f}/100\n\n"
            f"🚗 {listing.title}\n"
            f"📅 {listing.year} | 🛣️ {listing.km:,} km\n"
            f"⛽ {listing.fuel_type or '—'} | ⚙️ {listing.gear_type or '—'}\n\n"
            f"💰 *İlan Fiyatı:* {listing.price:,} TL\n"
            f"📊 Piyasa Ortalaması: {opp.market_median:,.0f} TL\n"
            f"✅ Tahmini Tasarruf: *{opp.discount_amount:,.0f} TL* (%{opp.discount_pct:.1f})\n\n"
            f"📍 {listing.location}\n"
            f"🏷️ Kaynak: {listing.source}\n"
            f"{conf_emoji} Güven: {opp.confidence} ({opp.sample_size} karş. araç)\n\n"
            f"🔗 [İlana Git]({listing.url})"
        )

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )
            logger.success(f"Telegram alert gönderildi: {listing.title}")
        except Exception as e:
            logger.error(f"Telegram alert hatası: {e}")

    async def send_summary(self, stats: dict):
        """Günlük özet raporu"""
        if not self._bot:
            return

        message = (
            f"📈 *Günlük Özet — Uniq Auto*\n\n"
            f"📦 Toplam aktif ilan: {stats.get('active', 0):,}\n"
            f"🆕 Bugün yeni: {stats.get('new_today', 0)}\n"
            f"🎯 Fırsatlar: {stats.get('opportunities', 0)}\n"
            f"💎 Ort. fiyat: {stats.get('avg_price', 0):,} TL\n\n"
            f"Sahibinden: {stats.get('by_source', {}).get('sahibinden', 0)}\n"
            f"Arabam: {stats.get('by_source', {}).get('arabam', 0)}"
        )

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Özet raporu gönderilemedi: {e}")
