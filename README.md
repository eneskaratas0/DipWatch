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
python -m collector yeniden-grupla    # mevcut veritabanındaki son 72 saati sıfırdan gruplar (bkz. "Veri kalitesi")
python -m tests.test_collector        # ağsız test (sahte beslemeler + sahte Claude)
python -m web                         # data/events.json -> public/ (site, bkz. aşağısı)
python -m collector dongu --site      # her turdan sonra siteyi de yeniden oluştur
python -m tests.test_telegram         # Telegram bildirimlerinin ağsız testi
python test_feeds.py sonuc.json       # sources.yaml'daki tüm beslemeleri (kapalılar dahil) gerçekten dener
python veri_kalite.py                 # veri kalitesi tanı raporu (bkz. "Veri kalitesi")
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

1. **Çekme**: 74 besleme paralel çekilir. Google News üzerinden gelenlerde başlıktaki " - Yayın" eki temizlenir.
   Linkler izleme parametrelerinden arındırılır. Üç düzeyde tekrar/çöp ayıklanır: aynı link ikinci kez eklenmez;
   aynı kaynaktan normalize edilmiş aynı başlık da eklenmez (Google News bazen aynı haberi farklı yönlendirme
   kimlikleriyle iki kez döndürür); kariyer/hakkımızda/abonelik/künye sayfaları gibi haber olmayan satırlar
   (`fetch.gecersiz_baslik_mi`) hiç haber sayılmaz. Kaynağa özel ek kurallar `sources.yaml`'da o kaynağın
   `haric:` listesine regex olarak eklenebilir. Her haber, başlık kalıbından ("Explainer: ...", "... - live")
   `haber` / `analiz` / `canli` içerik türü etiketi de alır (olay sayfasında diğer kaynağın yanında görünür).
2. **Gruplama**: başlık + açıklama TF-IDF vektörüne çevrilir; son 36 saatte güncellenen bir olayla benzerlik
   0.28'i geçerse o olaya eklenir, geçmezse yeni olay açılır (`config.py` içinden ayarlanır). Bir olayın vektörü
   katıldığı SON 15 haberle sınırlıdır (ilk haberin ağırlığı sonsuza kadar sabit kalıp olayı konudan
   uzaklaştırmasın) ve rakam/özel isim olması muhtemel terimler ekstra ağırlıklıdır (kalıp başlıklar -- "...
   Ödülü sahibini buldu" -- genelde yalnızca bu terimlerle ayrışır). "analiz"/"canli" etiketli haberler normalde
   kendi başına yeni bir olay açmasın diye yarı yarıya gevşetilmiş bir eşikle mevcut olaya bağlanmaya çalışılır.
3. **Diller arası ve gecikmiş birleştirme (anahtarsız)**: TF-IDF Türkçe ve İngilizce haberi eşleştiremez. Her
   başlık çok dilli bir gömme modeliyle (`paraphrase-multilingual-MiniLM-L12-v2`, fastembed ile bilgisayarda
   çalışır) anlam vektörüne çevrilir. Yalnızca o turda yeni açılan olaylara değil, son 72 saatte güncellenmiş
   TÜM aktif olaylara her turda yeniden bakılır ("periyodik birleştirme") -- aksi halde aynı olayın saatler/
   günler sonra başka dilde/kaynaktan açılan hali bir daha hiç karşılaştırılmaz. Benzerliği 0.85'i geçen en
   yakın çiftte az kaynaklı/daha yeni olan, köklü olana katılır. (Eşik kasıtlı olarak yüksek: periyodik
   birleştirmeyle bir olayın merkez vektörü büyüyüp genelleşince -- ör. "Houthi/Yemen" gibi -- daha düşük bir
   eşik, o ortak temadaki ilgisiz haberleri de kendine çekip 100+ habere varan sahte mega-olaylar oluşturabiliyordu;
   bkz. "Veri kalitesi".) Model ilk turda indirilir (~220 MB). İlk tur tüm başlıkları işlediği için ~5 dakika,
   sonraki turlar ~35 saniye sürer. Claude anahtarı varsa, kalan olaylar ayrıca tek bir Claude çağrısıyla kontrol edilir.
4. **Türkçe özet** (Claude anahtarı gerekir): en az 2 farklı kaynağı olan ve yeni haber almış olaylar özetlenir (tur başına en fazla 40).
   Özet; başlık, 2-4 cümle, bölge, ülkeler, etiketler ve 1-5 önem puanı içerir. Kaynaklar çelişiyorsa özette belirtilir.
   Anahtar yoksa olay başlığı, kümenin merkez (gömme) vektörüne en yakın başlık olur -- "Explainer"/"analysis"/
   "... - live" gibi kalıp başlıklar elenerek, eşitlikte Türkçe tercih edilerek. Gömme hiç çalışmadıysa en son
   Türkçe kaynağın başlığına, o da yoksa ilk haberin başlığına düşülür.
5. **Bölge**: Claude varsa olaya atadığı bölge kullanılır; yoksa `collector/bolge.py` başlık+özetteki ülke,
   şehir ve lider adlarından (TR+EN sözlük) çoğunluk oyuyla bölgeyi çıkarır -- kaynağın (beslemenin) bölgesi
   artık yalnızca içerik oyu eşit kaldığında son çare olarak kullanılır. Konu belirli bir bölgeye ait değilse
   (Nobel ödülleri, BM/WHO/IMF gibi küresel kurumlar, Olimpiyat/Dünya Kupası) ülke adı geçse de `kuresel`
   sayılır. Türkiye gündemi için `sources.yaml`'da ayrıca ayrı bir `turkiye` kaynak grubu var (Daily Sabah,
   Hürriyet Daily News, Bianet English, TRT Haber Türkiye, Anadolu Ajansı Güncel, NTV Gündem, Sözcü Gündem).

## Veri kalitesi

`python veri_kalite.py` (`--kaydet dosya.json` ile sonucu kaydeder, `--karsilastir once.json sonra.json` ile
iki kaydı karşılaştırır) `data/dipwatch.db` üzerinden haber olmayan satır sayısı, aynı kaynak+başlık tekrarı,
tahmini yanlış bölgeli olay oranı, merkezden belirgin uzak (konu dışı olması muhtemel) haber sayısı ve aynı
konunun kaç olaya bölündüğü gibi ölçümleri raporlar.

Düzeltmeler koddaki mantığı değiştirir ama veritabanındaki MEVCUT olayları kendiliğinden düzeltmez;
`python -m collector yeniden-grupla` son 72 saatin (ya da `--saat N` ile farklı bir pencerenin) haberlerini
mevcut olay atamalarından bağımsız olarak sıfırdan gruplar: haber olmayan satırları siler, pencere içindeki tam
tekrarları ayıklar, TF-IDF ile yeniden kümeler, gömme modeliyle (ve varsa Claude ile) birleştirir, özetler,
Telegram bildirim takibini (varsa) yeni kümelemeye göre senkronlar ve siteyi besleyen `events.json`'u yeniden
yazar. Çalışmadan önce veritabanının zaman damgalı bir yedeğini (`dipwatch.<zaman>.bak.db`) alır.

Bu komut aynı veritabanı üzerinde `python -m collector tur`/`dongu` ile **eşzamanlı çalıştırılmamalı** (ikisi
de aynı pencerede olay_id atar/taşır); bir dosya kilidi (`<db>.lock`) bunu zaten engeller ve kilit tutuluyorsa
açık bir hatayla durur -- `dongu` bunu yakalayıp bir sonraki turda yeniden dener, `tur`/`yeniden-grupla` tek
seferlik çalıştırmalarında hata doğrudan görünür. Kilit 30 dakikadan eskiyse (çökmüş bir süreçten kalmışsa)
kendiliğinden temizlenir; daha yeniyse ve eminsen elle silip tekrar deneyebilirsin.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `DIPWATCH_MODEL` | `claude-opus-5-5` | özet modeli |
| `DIPWATCH_EFOR` | `low` | düşünme eforu (low/medium/high) |
| `DIPWATCH_OZET_MIN_KAYNAK` | `2` | kaç kaynaklı olaylar özetlensin |
| `DIPWATCH_GOMME` | `1` | `0` yapılırsa gömme ile birleştirme kapanır |
| `DIPWATCH_GOMME_ESIGI` | `0.85` | düşürürsen daha çok, yükseltirsen daha az olay birleşir (düşürmeden önce "Veri kalitesi" bölümündeki mega-olay uyarısını oku) |
| `DIPWATCH_GOMME_PENCERE_SAAT` | `72` | birleştirme adayı aranacak pencere (olay_penceresi_saat'ten ayrı: durgunlaşmış ama hâlâ yakın zamanlı yinelenen olaylar da değerlendirilsin) |

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

Tasarım `.claude/skills/` altındaki `frontend-design` ve `ui-ux-pro-max` skill'lerine göre yapıldı: kâğıt rengi zemin,
başlıklarda Newsreader, arayüzde Public Sans yazı tipi; renk yalnızca bölgeyi gösterir. Ana sayfadaki renkli şerit,
birden fazla kaynaklı olayların bölgelere dağılımını gösterir ve bölge sayfalarına götürür. Koyu tema ve telefon ekranı desteklenir.
Yazı tipleri Google Fonts'tan gelir; internet yoksa sistem yazı tipleri kullanılır.

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

## Güvenlik

Proje, [OWASP Top 10](https://owasp.org/www-project-top-ten/) esas alınarak tarandı; sonuçlar
[`security-review-2026-10-08.md`](security-review-2026-10-08.md) dosyasında. Özet: SQL sorguları parametreli,
HTML/Telegram çıktıları `html.escape` ile kaçırılıyor, `.env` dışında hiçbir yerde anahtar yok; yüksek
güvenilirlikli bir açık bulunmadı.
