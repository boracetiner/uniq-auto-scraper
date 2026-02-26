# 🚗 Uniq Auto — Fırsat İlan Bulucu

sahibinden.com ve arabam.com'dan piyasa ortalamasının altındaki araçları
otomatik tarar ve Telegram'a anlık bildirim gönderir.

---

## Kurulum

### 1. Sistem gereksinimleri
- Python 3.11+
- PostgreSQL 14+ (ya da SQLite geliştirme için)
- Chromium (Playwright kurar)

### 2. Paketleri kur
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Ortam değişkenlerini ayarla
```bash
cp .env.example .env
# .env dosyasını düzenle
```

### 4. Telegram Bot Kurulumu
1. Telegram'da `@BotFather`'a mesaj at → `/newbot`
2. Bot token'ını `.env` dosyasına yaz
3. `@userinfobot`'tan kendi chat ID'ni al
4. `.env` dosyasına ekle

---

## Çalıştırma

```bash
# Sürekli çalışma (her 15 dk)
python main.py

# Tek seferlik tara
python main.py --once

# Tek marka tara
python main.py --brand BMW

# Test modu (verbose log)
python main.py --test
```

---

## Proje Yapısı

```
uniq_auto_scraper/
├── main.py                    ← Giriş noktası & scheduler
├── requirements.txt
├── .env.example
│
├── models/
│   └── listing.py             ← Pydantic veri modelleri
│
├── scrapers/
│   ├── base.py                ← Anti-detection, retry, browser yönetimi
│   ├── sahibinden.py          ← sahibinden.com scraper
│   ├── arabam.py              ← arabam.com scraper
│   └── orchestrator.py        ← Paralel çalıştırma & duplikat temizleme
│
├── db/
│   └── database.py            ← PostgreSQL / SQLite CRUD
│
├── utils/
│   └── price_engine.py        ← Fırsat skoru hesaplama
│
└── alerts/
    └── telegram_alert.py      ← Telegram bildirimleri
```

---

## Fırsat Skoru

| Skor | Anlam | İndirim |
|------|-------|---------|
| 80-100 🔥🔥🔥 | Çok büyük fırsat | %27+ altında |
| 65-80 🔥🔥 | Büyük fırsat | %22-27 altında |
| 50-65 🔥 | Fırsat | %17-22 altında |
| <50 | Normal | <17% altında |

Varsayılan bildirim eşiği: **60 puan** (`.env`'den ayarlanabilir)

---

## Filtre Özelleştirme

`scrapers/orchestrator.py` içindeki `DEFAULT_WATCH_FILTERS` listesini düzenle:

```python
ScrapeFilter(
    brands=["BMW"],
    price_min=1_500_000,
    price_max=3_000_000,
    year_min=2019,
    km_max=80_000,
    gear_types=["Otomatik"],
)
```

---

## Önemli Notlar

- **Rate limiting**: Scraper'lar 2-5 saniye rastgele bekleme yapar. Bunu kısaltma.
- **CAPTCHA**: Çok sık çekilirse CAPTCHA çıkabilir. `SCRAPE_INTERVAL_MINUTES=30` dene.
- **Terms of Service**: Kişisel ve ticari olmayan kullanım için tasarlanmıştır.
- **Veritabanı**: İlk scrape'te fiyat motoru çalışmaz (karşılaştırma verisi yok). 2-3 döngü sonra dolmaya başlar.
