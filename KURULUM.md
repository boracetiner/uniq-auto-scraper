# 🚀 Kurulum Rehberi — GitHub Actions + Supabase

Laptop'ına hiçbir şey kurmadan, tamamen ücretsiz çalışan sistem.

---

## Genel Bakış

```
sen → GitHub'a kodu yükle
         ↓
    GitHub Actions (her 30 dk)
    sahibinden + arabam'ı tara
         ↓
    Supabase (PostgreSQL)
    verileri kaydet
         ↓
    Telegram
    fırsatları bildir
```

---

## ADIM 1 — GitHub Hesabı Aç

1. https://github.com adresine git
2. "Sign up" → ücretsiz hesap aç
3. E-posta doğrulama yap

---

## ADIM 2 — Supabase (Ücretsiz PostgreSQL)

1. https://supabase.com adresine git
2. "Start your project" → ücretsiz hesap aç (GitHub ile de girebilirsin)
3. "New Project" tıkla:
   - Organization: kişisel hesabın
   - Name: `uniq-auto`
   - Database Password: güçlü bir şifre yaz → **kopyala, kaybet**
   - Region: `West EU (Ireland)` — Türkiye'ye en yakın ücretsiz bölge
4. "Create new project" → 2-3 dk bekle

5. Sol menüde **Settings → Database** → **Connection string** bölümü
6. **URI** sekmesini seç → şuna benzer bir string görürsün:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:5432/postgres
   ```
7. `[YOUR-PASSWORD]` kısmını az önce yazdığın şifreyle değiştir
8. Bu string'i bir yere kaydet → ileride lazım olacak

---

## ADIM 3 — Telegram Bot Kur

1. Telegram'ı aç → arama çubuğuna **@BotFather** yaz
2. `/newbot` yaz → Enter
3. Bot adı sor: `Uniq Auto` yaz
4. Kullanıcı adı sor: `uniqauto_fiyat_bot` gibi bir şey yaz (benzersiz olmalı)
5. Sana bir token verir: `7123456789:AAFxxxx...` → **kopyala**

6. Yeni arama → **@userinfobot** yaz → başlat
7. Sana Chat ID'ni söyler: `Id: 123456789` → **kopyala**

---

## ADIM 4 — Kodu GitHub'a Yükle

### GitHub Desktop kullan (en kolay)

1. https://desktop.github.com indir ve kur
2. Giriş yap
3. "Create New Repository":
   - Name: `uniq-auto-scraper`
   - Local path: zip'i çıkarttığın klasörü seç
   - Public/Private: **Private** seç (kodun gizli kalsın)
4. "Publish repository" tıkla → GitHub'a yüklendi

---

## ADIM 5 — Secrets Ekle (Şifreler GitHub'da Güvenli Saklanır)

1. GitHub'da repository sayfana git
2. **Settings** sekmesi (üstte)
3. Sol menü → **Secrets and variables → Actions**
4. **"New repository secret"** ile şunları tek tek ekle:

| Secret Adı | Değer |
|------------|-------|
| `DATABASE_URL` | Supabase'den aldığın postgresql:// string |
| `TELEGRAM_BOT_TOKEN` | BotFather'dan aldığın token |
| `TELEGRAM_CHAT_ID` | userinfobot'tan aldığın numara |
| `MIN_OPPORTUNITY_SCORE` | `60` |

---

## ADIM 6 — İlk Çalıştır (Test)

1. Repository sayfanda **Actions** sekmesine tıkla
2. Sol listede **"Uniq Auto — Fırsat Tarayıcı"** görünür
3. **"Run workflow"** → **"Run workflow"** butonuna tıkla
4. Yeşil daire çıkarsa başarılı ✅
5. Kırmızı çıkarsa → iş adımına tıkla → hata mesajını bana yaz

---

## Artık Otomatik!

Her 30 dakikada GitHub sunucuları scraper'ı çalıştıracak.
Fırsat ilan bulduğunda Telegram'a mesaj gelecek.
Sen hiçbir şey yapma gerekmiyor.

---

## Kontrol Paneli

GitHub Actions loglarını görmek için:
**Repository → Actions → En son çalışma → scrape job**

Her çalışmanın çıktısında şunu göreceksin:
```
INFO  Filtre 1/8: BMW | 500,000-1,500,000 TL
INFO  [Sahibinden] Sayfa 1: ...
SUCCESS Sayfa 1: 43 ilan çekildi
INFO  [Arabam] Sayfa 1: ...
SUCCESS Tarama tamamlandı (180s) | Çekilen: 320 | Yeni: 12 | Fırsat: 2
```

---

## Limit Bilgisi

- GitHub Actions: **2,000 dakika/ay** ücretsiz (her çalışma ~3 dk, ayda 600 çalışma = 1,800 dk → limit içinde)
- Supabase: **500 MB** ücretsiz (yüz binlerce ilan sığar)
- Telegram: Sınırsız ücretsiz
