# DipWatch

Uluslararası siyasetteki gelişmeleri izlemek için haber toplayıcı (2. adım) web sitesi (3. adım) ve Telegram bildirimleri (4. adım).

## Toplayıcı (2. adım)

`sources.yaml` içindeki beslemeleri düzenli aralıkla çeker, aynı olayı anlatan haberleri tek bir
**olay** altında toplar, Claude ile her olaya Türkçe başlık ve özet yazar, kaynak linklerini altında listeler.

## Kurulum ve çalıştırma

```bash
pip install -r requirements.txt
cp .env.example .env                  # sonra .env içine ANTHROPIC_API_KEY'i yaz (yoksa özetler atlanır)
python -m collector tur               # tek tur
python -m collector dongu --aralik 300  # her 5 dakikada bir
python -m collector feed-durum        # hangi besleme çalışıyor, hangisi hata veriyor
python -m tests.test_collector        # ağsız test (sahte beslemeler + sahte Claude)
python -m web                         # data/events.json -> public/ (site, bkz. aşağısı)
python -m collector dongu --site      # her turdan sonra siteyi de yeniden oluştur
python -m tests.test_telegram         # Telegram bildirimlerinin ağsız testi
```

## API anahtarı

Anahtarı https://console.anthropic.com/settings/keys adresinden al ve proje kökündeki `.env` dosyasına
`ANTHROPIC_API_KEY=sk-ant-...` olarak yaz. Toplayıcı bu dosyayı kendisi okur. `.env` `.gitignore` içinde
olduğu için GitHub'a gönderilmez; `git status` çıktısında görünmemesi gerekir.

## Çıktılar (`data/`)

- `dipwatch.db`: SQLite (haber, olay, feed_durum tabloları)
- `events.json`: son 72 saatin olayları; 3. adımdaki site bunu okuyacak
- `son_olaylar.md`: aynı listenin okunabilir hâli

## Nasıl çalışır

1. **Çekme**: 68 besleme paralel çekilir. Google News üzerinden gelenlerde başlıktaki " - Yayın" eki temizlenir.
   Linkler izleme parametrelerinden arındırılır, aynı link ikinci kez eklenmez.
2. **Gruplama**: başlık + açıklama TF-IDF vektörüne çevrilir; son 36 saatte güncellenen bir olayla
   benzerlik 0.28'i geçerse o olaya eklenir, geçmezse yeni olay açılır (`config.py` içinden ayarlanır).
3. **Diller arası birleştirme (anahtarsız)**: TF-IDF Türkçe ve İngilizce haberi eşleştiremez. Her başlık çok dilli
   bir gömme modeliyle (`paraphrase-multilingual-MiniLM-L12-v2`, fastembed ile bilgisayarda çalışır) anlam
   vektörüne çevrilir; yeni açılan bir olay, benzerliği 0.75'i geçen aktif olaya katılır. Model ilk turda indirilir
   (~220 MB). İlk tur tüm başlıkları işlediği için ~5 dakika, sonraki turlar ~35 saniye sürer.
   Claude anahtarı varsa, kalan olaylar ayrıca tek bir Claude çağrısıyla kontrol edilir.
4. **Türkçe özet** (Claude anahtarı gerekir): en az 2 farklı kaynağı olan ve yeni haber almış olaylar özetlenir (tur başına en fazla 40).
   Özet; başlık, 2-4 cümle, bölge, ülkeler, etiketler ve 1-5 önem puanı içerir. Kaynaklar çelişiyorsa özette belirtilir.
   Anahtar yoksa olay başlığı olarak varsa Türkçe bir kaynağın başlığı, yoksa ilk haberin başlığı kullanılır.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `DIPWATCH_MODEL` | `claude-opus-5-5` | özet modeli |
| `DIPWATCH_EFOR` | `low` | düşünme eforu (low/medium/high) |
| `DIPWATCH_OZET_MIN_KAYNAK` | `2` | kaç kaynaklı olaylar özetlensin |
| `DIPWATCH_GOMME` | `1` | `0` yapılırsa gömme ile birleştirme kapanır |
| `DIPWATCH_GOMME_ESIGI` | `0.75` | düşürürsen daha çok, yükseltirsen daha az olay birleşir |

Bozuk bir beslemeyi kapatmak için `sources.yaml` içinde `durum: kapali` yazmak yeterli.

## Web sitesi (3. adım)

`python -m web`, `data/events.json` dosyasından `public/` klasörüne statik bir site üretir. API anahtarı, sunucu
veya ek paket gerekmez (yalnızca Python standart kütüphanesi). `public/index.html` dosyasını tarayıcıda açmak yeterli;
istenirse klasör olduğu gibi GitHub Pages, Netlify vb. bir yere konabilir (linkler göreli).

- **Ana sayfa**: son 72 saatin olayları, son haberin günüyle (İstanbul saati) gruplu. Önemli ve çok kaynaklı olaylar üstte.
- **Bölge sayfaları** (`bolge/orta_dogu.html` …): aynı liste, tek bölge.
- **Olay sayfası** (`olay/<id>.html`): Türkçe özet (yoksa kaynak başlığı), ülke/etiketler, haberlerin zamana göre
  sıralı **zaman çizelgesi** ve yayın kuruluşuna göre gruplu **tüm kaynak linkleri**.
- Listelerde arama kutusu ve "tek kaynaklı olayları da göster" seçeneği var. Varsayılan olarak yalnızca birden fazla
  kaynağın haber yaptığı olaylar görünür (tek kaynaklı haberlerin çoğu gürültü). JavaScript kapalıysa hepsi görünür.

Site her çalıştırmada `events.json`'dan baştan üretilir; süresi dolan olayların sayfaları silinir.
`python -m web --girdi baska.json --cikti baska_klasor/` ile yollar değiştirilebilir. Test: `python -m tests.test_web`.

## Telegram bildirimleri (4. adım)

Seçtiğin bölgelerde veya anahtar kelimelerde **yeni bir olay** çıktığında (en az 2 farklı kaynak haber yapınca) ya da
bildirilmiş bir olay **büyüdüğünde** (3 yeni kaynak daha gelince) Telegram'a mesaj gelir. Mesajda Türkçe başlık
(varsa özet), bölge, kaynak sayısı ve kaynak linkleri bulunur. Büyüme mesajı, ilk mesaja yanıt olarak gelir; böylece bir
olayın gelişimi Telegram'da tek bir zincirde görünür. Toplayıcı her turun sonunda bunu kendiliğinden yapar
(`python -m collector dongu`); `.env` içinde bot bilgileri yoksa bu adım sessizce atlanır.

### 1. BotFather ile bot oluştur

1. Telegram'da **@BotFather** hesabını aç (mavi tikli olan) ve **Başlat**'a bas.
2. `/newbot` yaz.
3. Botun görünen adını yaz, ör. `DipWatch`.
4. Kullanıcı adını yaz; `bot` ile bitmeli ve daha önce alınmamış olmalı, ör. `dipwatch_enes_bot`.
5. BotFather `123456789:AAH...` biçiminde bir **anahtar (token)** verir. Bu bir şifredir: kimseyle paylaşma,
   GitHub'a koyma. Proje kökündeki `.env` dosyasına ekle:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   ```

### 2. Sohbet kimliğini (chat id) bul

1. Telegram'da yeni botunu aç (BotFather'ın verdiği `t.me/...` linki) ve **Başlat**'a bas ya da herhangi bir mesaj yaz.
   Bildirimler bir gruba gelsin istiyorsan botu gruba ekle ve grupta `/start` yaz.
2. Bilgisayarında şunu çalıştır:
   ```bash
   python -m collector telegram-chat-id
   ```
   Çıktıdaki satırı (ör. `TELEGRAM_CHAT_ID=987654321`) olduğu gibi `.env` dosyasına ekle. Grupların kimliği eksiyle
   başlar (ör. `-100...`), eksi işaretini de yaz.
3. Deneme mesajı gönder:
   ```bash
   python -m collector telegram-test
   ```
   Telegram'da "bağlantı testi" mesajını görüyorsan kurulum tamam.

`.env` dosyası `.gitignore` içinde olduğu için GitHub'a gönderilmez; `git status` çıktısında görünmemesi gerekir.

### 3. Neyin bildirileceğini seç: `bildirim.yaml`

```yaml
bolgeler: [orta_dogu]                 # orta_dogu, rusya_ukrayna_kafkasya, avrupa, asya_pasifik, afrika, amerika, turkiye, kuresel
anahtar_kelimeler: [İran, Iran, Gazze, Gaza, NATO]
min_kaynak: 2                         # kaç farklı kaynak haber yapınca bildirilsin
min_onem: 0                           # 1-5, yalnızca Claude özeti olan olaylarda (0 = dikkate alma)
buyume_esigi: 3                       # kaç yeni kaynakta güncelleme gelsin (0 = kapalı)
tur_basina_en_fazla: 10               # bir turda en fazla kaç mesaj
```

Bölgeye **veya** anahtar kelimeye uyması yeterli; ikisi de boşsa her olay bildirilir. Anahtar kelimeler başlık, özet,
ülkeler, etiketler ve kaynak başlıklarında aranır; büyük/küçük ve Türkçe harf farkı önemsizdir (İran = Iran) ve
kelime başından eşleşir ("İran" → "Iranian" yakalanır, "NATO" → "senator" yakalanmaz). Haberlerin çoğu İngilizce
olduğu için kelimenin İngilizcesini de yazmak iyi olur. Claude anahtarı yoksa olayın bölgesi tahmindir ve bazen
yanılır; önemli konular için anahtar kelime daha güvenilirdir. Dosya her turda yeniden okunur, toplayıcıyı yeniden
başlatmak gerekmez.

**İlk çalıştırma**: son 72 saatin yüzlerce olayını birden göndermemek için ilk turda yalnızca "bildirimler açıldı"
mesajı gelir ve o anki olaylar görüldü sayılır. Bundan sonra çıkan yeni ve büyüyen olaylar bildirilir.
