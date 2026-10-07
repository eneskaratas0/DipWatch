# OWASP Top 10 Güvenlik Taraması — DipWatch

**Tarih:** 2026-10-08

**Kapsam:** `collector/*.py`, `web/*.py`, `web/statik/filtre.js`, `bildirim.yaml`, `sources.yaml`, `.env.example`, `requirements.txt` (`.claude/skills/**` ve `tests/**` hariç — araç/test dosyaları).

## Sonuç: Yüksek güvenilirlikli (confidence ≥ 8) bir bulgu yok.

İki ayrı taramada (ilk geçiş + ikinci doğrulama ajanı) toplam bir aday bulgu çıktı, o da false-positive filtresinden geçemedi:

| Aday | Kategori | Sonuç |
|---|---|---|
| `collector/fetch.py:38-50` — redirect takibi sırasında host/protokol kısıtlaması yok | A10 SSRF | **Elendi (3/10)** — sömürmek için güvenilir bir haber kaynağının ele geçirilmesi/DNS hijack/MITM gerekiyor; bu DipWatch'ın kendi saldırı yüzeyi dışında, ayrı bir önkoşul. Ayrıca yanıt hiçbir yere yansıtılmıyor (kör istek, kanıtlanmış etki yok). İlke bazlı (CWE-918) ama somut değil. |

### Neden temiz çıktı

- **Injection (A03):** Tüm SQL sorguları (`db.py`, `cluster.py`, `telegram.py`, `export.py`, `summarize.py`) parametreli (`?`). `eval`/`exec`/`os.system`/`subprocess`/`pickle` hiçbir yerde yok. YAML her yerde `yaml.safe_load`.
- **XSS:** `web/build.py` ve `collector/telegram.py` tüm dinamik alanları `html.escape` ile kaçırıyor; `guvenli_link()` href'leri sadece http/https ile sınırlıyor (`javascript:` engelleniyor).
- **Sızdırılan sır (A02/A07):** `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` sadece ortam değişkenlerinden/`.env`'den okunuyor (gitignore'da); kod içinde hardcoded anahtar yok.
- **Path traversal:** Dosya adları olay tablosunun auto-increment id'si veya sabit bir enum'dan (`BOLGELER`) geliyor — dışarıdan enjekte edilemiyor.
- **SSRF/erişim kontrolü:** Giden istekler sadece maintainer'ın `sources.yaml`'ında tanımlı adreslere gidiyor; tek kullanıcılı araçta yetkilendirme modeli yok, bu bağlamda anlamsız.

**Özet:** Proje küçük ama güvenlik pratiği olarak temiz; OWASP Top 10 kapsamında somut, sömürülebilir bir açık bulunamadı.
