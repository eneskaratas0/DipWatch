# DipWatch

**Türkçe** | [English](README.en.md)

Uluslararası siyasetteki gelişmeleri yerel ve uluslararası haber kaynaklarından otomatik olarak toplayan, aynı olayı
anlatan haberleri tek bir "olay" altında gruplayan ve her olay için kaynaklarıyla birlikte Türkçe özet sunan bir
izleme sistemi.

- Canlı site: https://eneskaratas0.github.io/DipWatch/
- Ayrıntılı teknik kılavuz (kurulum, komutlar, ayarlar): [docs/TEKNIK.md](docs/TEKNIK.md)

Bu belge, projeyi bir araştırma yöntemi metni düzeninde anlatır: problem, tasarım, veri kaynakları ve örneklem,
veri toplama, analiz, geçerlilik, sınırlılıklar ve etik.

---

## İçindekiler

1. [Özet](#1-özet)
2. [Araştırma problemi ve amaç](#2-araştırma-problemi-ve-amaç)
3. [Araştırma tasarımı](#3-araştırma-tasarımı)
4. [Veri kaynakları ve örneklem](#4-veri-kaynakları-ve-örneklem)
5. [Veri toplama](#5-veri-toplama)
6. [Veri işleme ve analiz](#6-veri-işleme-ve-analiz)
7. [Geçerlilik ve güvenilirlik](#7-geçerlilik-ve-güvenilirlik)
8. [Sınırlılıklar ve olası yanlılıklar](#8-sınırlılıklar-ve-olası-yanlılıklar)
9. [Etik ve hukuki hususlar](#9-etik-ve-hukuki-hususlar)
10. [Bulguların sunumu: çıktılar](#10-bulguların-sunumu-çıktılar)
11. [Kullanım](#11-kullanım)
12. [Proje yapısı](#12-proje-yapısı)

---

## 1. Özet

DipWatch, 10 kaynak grubunda toplam 74 haber beslemesini her 30 dakikada bir tarar. Toplanan haberler önce sözcük
benzerliğine (TF-IDF), ardından çok dilli anlam benzerliğine (gömme modeli) göre olaylara ayrılır. En az iki farklı
kaynağın haber yaptığı olaylar bir büyük dil modeliyle (LLM) Türkçe olarak özetlenir; özet, olayın bölgesini, ilgili
ülkeleri ve 1-5 arası bir önem puanını içerir. Sonuçlar statik bir web sitesinde ve isteğe bağlı Telegram
bildirimleriyle sunulur. Her özetin altında, özete temel olan tüm kaynak haberlerin linkleri yer alır.

## 2. Araştırma problemi ve amaç

**Problem.** Uluslararası bir gelişme, farklı ülkelerin basınında farklı dillerde, farklı zamanlarda ve farklı
anlatılarla yer alır. Tek bir okurun bu kaynakları elle taraması zaman alır; tek bir kaynağa dayanmak ise bakış
açısını daraltır.

**Amaç.** Bölgesel ve küresel kaynakları sistematik biçimde izleyip aynı olaya ait haberleri bir araya getirmek, olayı
tarafsız bir Türkçe özetle sunmak ve okuru her zaman özgün kaynaklara yönlendirmek.

**Araştırma soruları.**

1. Farklı dil ve ülkelerdeki kaynaklardan gelen haberler, aynı olay altında otomatik olarak ne kadar doğru gruplanabilir?
2. Bir olay hangi kaynaklarda, hangi sırayla ve hangi farklı anlatılarla yer alıyor?
3. Hangi bölgelerde, hangi olaylar birden fazla kaynağın gündemine giriyor?

## 3. Araştırma tasarımı

| Öğe | Seçim |
|---|---|
| Tür | Betimleyici, sürekli (boylamsal) izleme; otomatik içerik toplama ve hesaplamalı metin analizi |
| Analiz birimi | **Olay**: aynı somut gelişmeyi (aynı saldırı, görüşme, açıklama) anlatan haberlerin kümesi |
| Gözlem birimi | **Haber**: bir kaynağın yayımladığı tek bir içerik (başlık, kısa açıklama, link, zaman) |
| Zaman penceresi | Sitede son 72 saat; bir olaya 36 saat yeni haber gelmezse olay kapanır |
| Ölçüm sıklığı | 30 dakikada bir (GitHub Actions üzerinde) |
| Yaklaşım | Kurala dayalı ve tekrarlanabilir eşikler (TF-IDF, gömme) ile LLM destekli özetlemenin birleşimi |

## 4. Veri kaynakları ve örneklem

**Örnekleme yöntemi:** amaçlı (purposive) örnekleme. Kaynaklar rastgele değil, aşağıdaki ölçütlere göre seçildi:

- **Bölgesel kapsam:** her bölge için o bölgenin kendi basını ("yerel") ile küresel ajans ve yayıncılar birlikte.
- **Bakış açısı çeşitliliği:** çatışmanın farklı taraflarından kaynaklar (ör. İsrail basını ile Arap ve İran basını;
  Ukrayna basını ile Rus devlet ajansı TASS ve Rus muhalif yayınlar).
- **Dil:** İngilizce ve Türkçe kaynaklar.
- **Tür:** haber ajansları, gazeteler, düşünce kuruluşları ve resmî kaynaklar.
- **Erişilebilirlik:** RSS akışı olan ya da Google News üzerinden "site:" sorgusuyla izlenebilen, ücretsiz erişilen kaynaklar.

**Kaynak grupları** (tam liste ve alanlar: [`sources.yaml`](sources.yaml)):

| Grup | Sayı | Kaynaklar |
|---|---:|---|
| Küresel | 9 | BBC World, Reuters, AP, Al Jazeera English, The Guardian, France 24, DW, New York Times, NPR |
| Orta Doğu | 14 | BBC Middle East, Al-Monitor, Middle East Eye, Times of Israel, Haaretz, Jerusalem Post, Arab News, Asharq Al-Awsat, Al Arabiya, The National, Tehran Times, Iran International, L'Orient Today, Rudaw |
| Rusya, Ukrayna, Kafkasya | 8 | Kyiv Independent, Ukrainska Pravda, TASS, Meduza, The Moscow Times, RFE/RL, OC Media, Eurasianet |
| Avrupa | 5 | Politico Europe, Euronews, EUobserver, Balkan Insight, BBC Europe |
| Asya-Pasifik | 9 | South China Morning Post, Global Times, Nikkei Asia, The Japan Times, Yonhap, The Diplomat, The Hindu, Dawn, BBC Asia |
| Afrika | 5 | BBC Africa, AllAfrica, Africanews, Premium Times, The East African |
| Amerika | 3 | BBC US & Canada, BBC Latin America, MercoPress |
| Türkiye | 7 | Daily Sabah, Hürriyet Daily News, Bianet English, TRT Haber, Anadolu Ajansı, NTV, Sözcü |
| Türkçe dünya haberleri | 7 | AA Dünya, TRT Haber Dünya, BBC Türkçe, DW Türkçe, Euronews Türkçe, Independent Türkçe, Medyascope |
| Analiz ve resmî | 7 | International Crisis Group, Foreign Policy, CFR, Carnegie, SETA, ORSAM, UN News |

Dağılım: 61 İngilizce, 13 Türkçe besleme; 50'si kaynağın kendi RSS akışından, 24'ü Google News üzerinden.

Ayrı bir modül, teknoloji ve siber güvenlik haberlerini de izler (The Hacker News, BleepingComputer, Krebs on
Security, The Record, CISA, Ars Technica; bkz. [`teknoloji/kaynaklar.yaml`](teknoloji/kaynaklar.yaml)).

## 5. Veri toplama

- **Araç:** Python toplayıcısı (`collector/`), `feedparser` ile RSS okuma.
- **Yöntem:** Her kaynak kendi RSS akışından çekilir. RSS'i olmayan ya da bot korumasıyla erişimi engelleyen
  kaynaklar, Google News'te `site:alanadi when:1d` sorgusuyla izlenir (Türkçe kaynaklar Google News Türkiye
  baskısında aranır).
- **Toplanan alanlar:** başlık, kısa açıklama, link, yayın zamanı, kaynak adı, kaynağın bölgesi ve dili. Haberin tam
  metni toplanmaz.
- **Kayıt:** SQLite veritabanı (`data/dipwatch.db`); veritabanı turlar arasında korunur, böylece veri zaman içinde birikir.
- **Kaynak sağlığı:** her beslemenin son durumu (çalışıyor, hata, boş) kaydedilir (`python -m collector feed-durum`).

## 6. Veri işleme ve analiz

1. **Ön işleme ve temizlik.** Linkler izleme parametrelerinden arındırılır; Google News başlıklarındaki "- Yayın" eki
   silinir. Aynı link ya da aynı kaynaktan aynı başlık ikinci kez kaydedilmez. Kariyer, abonelik, künye gibi haber
   olmayan satırlar elenir. Her habere başlık kalıbından bir içerik türü etiketi verilir: `haber`, `analiz`, `canli`.
2. **Olay kümeleme (sözcük düzeyi).** Başlık ve açıklama TF-IDF vektörüne çevrilir. Son 36 saatte güncellenen bir
   olayla kosinüs benzerliği 0,28'i geçen haber o olaya eklenir, geçmeyen yeni olay açar. Olayın vektörü son 15
   haberle sınırlıdır; özel isim ve rakamlara ekstra ağırlık verilir.
3. **Diller arası birleştirme (anlam düzeyi).** TF-IDF Türkçe ve İngilizce haberi eşleştiremediği için her başlık çok
   dilli bir gömme modeliyle (`paraphrase-multilingual-MiniLM-L12-v2`) anlam vektörüne çevrilir. Son 72 saatteki
   olaylardan benzerliği 0,85'i geçen çiftler birleştirilir. Eşik, ilgisiz haberleri toplayan "mega olaylar"
   oluşmasın diye bilinçli olarak yüksek tutuldu.
4. **Bölge sınıflandırması.** LLM özeti varsa onun bölgesi kullanılır. Yoksa başlık ve özetteki ülke, şehir ve lider
   adlarından (Türkçe ve İngilizce sözlük) çoğunluk oyuyla bölge belirlenir. Belirli bir bölgeye ait olmayan konular
   (BM, Nobel, Olimpiyatlar gibi) "küresel" sayılır.
5. **Özetleme (nitel sentez).** En az 2 farklı kaynağı olan olaylar bir LLM ile (Claude, Gemini ya da Groq) özetlenir.
   Modele verilen talimat: yalnızca verilen haberlerdeki bilgiyi kullanmak, tahmin eklememek, kaynaklar çelişiyorsa ya
   da farklı anlatılar sunuyorsa bunu açıkça belirtmek. Çıktı sabit bir şemaya uyar: başlık, 2-4 cümle özet, bölge,
   ülkeler, etiketler, 1 (rutin) ile 5 (büyük kriz) arası önem puanı. LLM kullanılamazsa olayın en temsilî başlığı
   gösterilir ya da başlık makine çevirisiyle Türkçeye çevrilip "makine çevirisi" notuyla işaretlenir.

## 7. Geçerlilik ve güvenilirlik

- **Kaynak şeffaflığı:** her özetin altında, özetin dayandığı tüm haberlerin linkleri ve zaman çizelgesi bulunur;
  okur her iddiayı özgün kaynağında doğrulayabilir.
- **Üçgenleme:** yalnızca en az iki bağımsız kaynağın haber yaptığı olaylar özetlenir ve varsayılan olarak listelenir;
  tek kaynaklı haberler isteğe bağlı olarak gösterilir.
- **Tekrarlanabilirlik:** kümeleme eşikleri sabittir ve [`collector/config.py`](collector/config.py) içinde ya da ortam
  değişkenleriyle açıkça tanımlıdır; aynı veriyle aynı kümeler oluşur. `python -m collector yeniden-grupla` bir zaman
  penceresini sıfırdan yeniden gruplar.
- **Veri kalitesi ölçümü:** [`veri_kalite.py`](veri_kalite.py) haber olmayan satır oranını, tekrarları, tahmini yanlış
  bölgeli olayları, kümenin merkezinden uzak (konu dışı olası) haberleri ve aynı konunun kaç olaya bölündüğünü raporlar;
  iki ölçüm birbiriyle karşılaştırılabilir.
- **Testler:** ağ bağlantısı gerektirmeyen testler, sahte beslemeler ve sahte model yanıtlarıyla toplayıcıyı, siteyi,
  Telegram bildirimlerini ve teknoloji modülünü sınar (`tests/`).

## 8. Sınırlılıklar ve olası yanlılıklar

- **Seçim yanlılığı:** kaynak listesi amaçlı örneklemdir; dünya basınının temsilî bir örneklemi değildir. İngilizce
  kaynaklar ağırlıktadır (74 beslemeden 61'i) ve Batı merkezli küresel yayıncıların payı yüksektir. Arapça, Farsça,
  Rusça, Çince gibi dillerdeki yerel basın çoğunlukla bu kuruluşların İngilizce yayınları üzerinden temsil edilir.
- **Erişim kaynaklı eksiklik:** RSS akışları her haberi içermeyebilir; Google News üzerinden izlenen kaynaklarda
  Google'ın kendi sıralaması ve filtresi devrededir. Ücretli duvarın arkasındaki içerik toplanmaz.
- **Yalnızca başlık ve kısa açıklama:** analiz haberin tam metnine değil başlık ve özete dayanır; ayrıntı ve bağlam kaybolabilir.
- **Kümeleme hataları:** benzer kalıptaki farklı olaylar birleşebilir (yanlış pozitif), farklı kelimelerle yazılmış aynı
  olay ayrı kalabilir (yanlış negatif). Eşikler bu iki hata arasında bir dengedir.
- **LLM sınırlılıkları:** özetler hatalı genelleme ya da yanlış vurgu içerebilir; önem puanı modelin yargısıdır ve
  nesnel bir ölçüm değildir. Ücretsiz modellerin kotası dolduğunda bazı olaylar özetsiz kalır.
- **Bölge ataması:** LLM yokken sözlüğe dayalı bölge tahmini zaman zaman yanılır.
- **Zaman sınırı:** sistem son 72 saate odaklanır; uzun vadeli arşiv analizi için tasarlanmamıştır.

## 9. Etik ve hukuki hususlar

- **Telif:** haberlerin tam metni kopyalanmaz, yeniden yayımlanmaz. Yalnızca başlık, kısa açıklama ve özgün habere
  link kullanılır; okur her zaman kaynağa yönlendirilir.
- **Kaynak gösterme:** her özet, dayandığı yayın kuruluşlarını ve linkleri açıkça gösterir.
- **Kişisel veri:** kullanıcı verisi ya da kişisel veri toplanmaz; yalnızca herkese açık haber başlıkları işlenir.
  Ücretsiz LLM katmanlarına gönderilen içerik de yalnızca bu herkese açık başlık ve açıklamalardır.
- **Erişim kurallarına saygı:** bot korumasıyla erişimi engelleyen sitelerde koruma atlatılmaz, Google News gibi açık
  bir kanal kullanılır.
- **Tarafsızlık:** özet talimatı tarafsız dil ister ve kaynaklar arasındaki anlatı farklarının gizlenmeden
  belirtilmesini şart koşar. Otomatik özetler editoryal bir yorum ya da doğrulanmış bilgi yerine geçmez.
- **Güvenlik:** API anahtarları ve Telegram bot bilgileri yalnızca yerel `.env` dosyasında ya da GitHub Actions
  gizli değişkenlerinde tutulur, depoya konmaz. OWASP Top 10'a göre yapılan tarama:
  [`security-review-2026-10-08.md`](security-review-2026-10-08.md).

## 10. Bulguların sunumu: çıktılar

- **Web sitesi** (https://eneskaratas0.github.io/DipWatch/): son 72 saatin olayları, güne ve öneme göre sıralı;
  bölge sayfaları; her olay için Türkçe özet, zaman çizelgesi ve yayın kuruluşuna göre gruplu kaynak linkleri;
  arama; koyu tema ve telefon desteği. Ayrıca "Teknoloji & Siber" sayfası.
- **Telegram bildirimleri:** seçilen bölge ya da anahtar kelimelerde yeni bir olay çıktığında ya da bildirilmiş bir olay
  büyüdüğünde mesaj gelir ([`bildirim.yaml`](bildirim.yaml)).
- **Veri dosyaları:** `data/events.json` (makinece okunabilir), `data/son_olaylar.md` (okunabilir liste),
  `data/teknoloji.json`.

## 11. Kullanım

```bash
pip install -r requirements.txt
cp .env.example .env                 # isteğe bağlı: LLM anahtarı ve Telegram bilgileri
python -m collector tur --site public  # bir tur topla, grupla, özetle ve siteyi üret
python -m collector dongu --aralik 300 --site  # her 5 dakikada bir
python -m collector feed-durum       # kaynakların durumu
python veri_kalite.py                # veri kalitesi raporu
python -m tests.test_collector       # ağsız test
```

API anahtarı olmadan da çalışır; bu durumda özetler yerine temsilî başlık ya da makine çevirisi gösterilir.
Ücretsiz seçenekler (Gemini, Groq), tüm ayarlar, Telegram kurulumu ve GitHub Pages yayını için:
[docs/TEKNIK.md](docs/TEKNIK.md).

## 12. Proje yapısı

```
sources.yaml          kaynak listesi (örneklem)
collector/            veri toplama, kümeleme, birleştirme, bölge, özet, Telegram
teknoloji/            teknoloji ve siber güvenlik modülü
web/                  statik site üretici
tests/                ağsız testler
veri_kalite.py        veri kalitesi ölçümü
bildirim.yaml         Telegram bildirim tercihleri
.github/workflows/    30 dakikalık otomatik toplama ve yayın
docs/TEKNIK.md        ayrıntılı teknik kılavuz (Türkçe)
```
