# DipWatch

Uluslararası siyasetteki gelişmeleri izlemek için haber toplayıcı (2. adım) ve web sitesi (3. adım).

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

Tasarım `.claude/skills/` altındaki `frontend-design` ve `ui-ux-pro-max` skill'lerine göre yapıldı: kâğıt rengi zemin,
başlıklarda Newsreader, arayüzde Public Sans yazı tipi; renk yalnızca bölgeyi gösterir. Ana sayfadaki renkli şerit,
birden fazla kaynaklı olayların bölgelere dağılımını gösterir ve bölge sayfalarına götürür. Koyu tema ve telefon ekranı desteklenir.
Yazı tipleri Google Fonts'tan gelir; internet yoksa sistem yazı tipleri kullanılır.

Site her çalıştırmada `events.json`'dan baştan üretilir; süresi dolan olayların sayfaları silinir.
`python -m web --girdi baska.json --cikti baska_klasor/` ile yollar değiştirilebilir. Test: `python -m tests.test_web`.
