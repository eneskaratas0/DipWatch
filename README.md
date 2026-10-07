# DipWatch toplayıcı (2. adım)

`sources.yaml` içindeki beslemeleri düzenli aralıkla çeker, aynı olayı anlatan haberleri tek bir
**olay** altında toplar, Claude ile her olaya Türkçe başlık ve özet yazar, kaynak linklerini altında listeler.

## Kurulum ve çalıştırma

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # yoksa özetler atlanır, gruplama yine çalışır
python -m collector tur               # tek tur
python -m collector dongu --aralik 300  # her 5 dakikada bir
python -m collector feed-durum        # hangi besleme çalışıyor, hangisi hata veriyor
python -m tests.test_collector        # ağsız test (sahte beslemeler + sahte Claude)
```

## Çıktılar (`data/`)

- `dipwatch.db`: SQLite (haber, olay, feed_durum tabloları)
- `events.json`: son 72 saatin olayları; 3. adımdaki site bunu okuyacak
- `son_olaylar.md`: aynı listenin okunabilir hâli

## Nasıl çalışır

1. **Çekme**: 68 besleme paralel çekilir. Google News üzerinden gelenlerde başlıktaki " - Yayın" eki temizlenir.
   Linkler izleme parametrelerinden arındırılır, aynı link ikinci kez eklenmez.
2. **Gruplama**: başlık + açıklama TF-IDF vektörüne çevrilir; son 36 saatte güncellenen bir olayla
   benzerlik 0.28'i geçerse o olaya eklenir, geçmezse yeni olay açılır (`config.py` içinden ayarlanır).
3. **Diller arası birleştirme**: TF-IDF Türkçe ve İngilizce haberi eşleştiremez. Her turda yeni açılan
   olaylar tek bir Claude çağrısıyla mevcut olaylara karşı kontrol edilir ve aynıysa birleştirilir.
4. **Türkçe özet**: en az 2 farklı kaynağı olan ve yeni haber almış olaylar özetlenir (tur başına en fazla 40).
   Özet; başlık, 2-4 cümle, bölge, ülkeler, etiketler ve 1-5 önem puanı içerir. Kaynaklar çelişiyorsa özette belirtilir.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `DIPWATCH_MODEL` | `claude-opus-5-5` | özet modeli |
| `DIPWATCH_EFOR` | `low` | düşünme eforu (low/medium/high) |
| `DIPWATCH_OZET_MIN_KAYNAK` | `2` | kaç kaynaklı olaylar özetlensin |

Bozuk bir beslemeyi kapatmak için `sources.yaml` içinde `durum: kapali` yazmak yeterli.
