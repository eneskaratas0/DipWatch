"""Ağsız uçtan uca test: sahte RSS dosyaları (file://) + sahte Claude istemcisi.

Çalıştırma:  cd /mnt/project-files/dipwatch && python3 -m tests.test_collector
Haber içerikleri test için uydurulmuştur, gerçek değildir.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

from collector import __main__ as ana
from collector import db
from collector.config import Ayarlar

SIMDI = datetime.now(timezone.utc)

FEEDS = {
    "bbc": ("BBC World", "kuresel", "en", [
        ("Iran and IAEA hold talks in Vienna on nuclear inspections",
         "Iranian officials met the UN nuclear watchdog in Vienna to discuss resuming inspections at enrichment sites.", 3),
        ("Sudan: RSF fighters attack El Fasher camp, dozens killed",
         "The paramilitary Rapid Support Forces attacked a displacement camp near El Fasher in Darfur.", 5),
        ("EU agrees new sanctions package against Russia",
         "European Union ambassadors agreed a new package of sanctions targeting Russian energy exports and shadow fleet tankers.", 2),
    ]),
    "aj": ("Al Jazeera English", "kuresel", "en", [
        ("Iran, IAEA resume talks in Vienna over nuclear inspections",
         "Tehran and the International Atomic Energy Agency held talks in Vienna on access for inspectors.", 2),
        ("Dozens killed as RSF attacks camp near El Fasher in Sudan's Darfur",
         "Rapid Support Forces stormed a displacement camp close to El Fasher, local monitors said.", 4),
        ("Japan's ruling party picks new leader ahead of election",
         "Japan's Liberal Democratic Party chose a new leader on Saturday.", 6),
    ]),
    "pol": ("Politico Europe", "avrupa", "en", [
        ("EU sanctions package hits Russian shadow fleet tankers and energy exports",
         "Ambassadors in Brussels signed off on the latest sanctions package against Russia.", 1),
    ]),
    "aa": ("Anadolu Ajansı Dünya", "turkce", "tr", [
        ("İran ile UAEA Viyana'da nükleer denetimleri görüştü",
         "İranlı yetkililer Uluslararası Atom Enerjisi Ajansı ile Viyana'da bir araya geldi.", 1),
    ]),
}


def rss(ad, ogeler):
    items = "".join(
        f"<item><title>{t}</title><link>https://ornek.test/{ad}/{i}</link>"
        f"<description>{d}</description><pubDate>{format_datetime(SIMDI - timedelta(hours=h))}</pubDate></item>"
        for i, (t, d, h) in enumerate(ogeler))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{ad}</title>{items}</channel></rss>'


class SahteClaude:
    """client.beta.messages.create(...) arayüzünü taklit eder."""
    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self.cagrilar = []

    def create(self, **kw):
        self.cagrilar.append(kw)
        icerik = kw["messages"][0]["content"]
        if "YENİ:" in icerik:  # birleştirme isteği: Türkçe İran haberini İngilizce olayla eşleştir
            yeni = [l for l in icerik.split("\n\nMEVCUT:")[0].splitlines()[1:] if "UAEA" in l]
            mevcut = [l for l in icerik.split("\n\nMEVCUT:\n")[1].splitlines() if "IAEA" in l]
            es = [{"yeni": int(yeni[0].split(":")[0]), "mevcut": int(mevcut[0].split(":")[0])}] if yeni and mevcut else []
            veri = {"eslesmeler": es}
        else:
            veri = {"baslik": "Test başlığı", "ozet": "Test özeti.", "bolge": "orta_dogu",
                    "ulkeler": ["İran"], "etiketler": ["nükleer"], "onem": 3}
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(veri, ensure_ascii=False))])


def sahte_gomucu(metinler):
    """Konu anahtar kelimesine göre aynı vektörü verir: UAEA (Türkçe) ve IAEA (İngilizce) aynı konu."""
    import numpy as np
    konular = [("IAEA", "UAEA"), ("RSF",), ("sanctions",), ("Japan",)]
    v = np.zeros((len(metinler), len(konular) + 1), dtype=np.float32)
    for i, m in enumerate(metinler):
        k = next((n for n, kel in enumerate(konular) if any(x in m for x in kel)), len(konular))
        v[i, k] = 1
    return v


def ortam_kur(feeds=FEEDS):
    """Sahte beslemeleri ve sources.yaml'ı geçici bir klasöre yazar, ayarları döndürür."""
    tmp = Path(tempfile.mkdtemp())
    src = ["bolgeler:"]
    for anahtar, (ad, bolge, dil, ogeler) in feeds.items():
        (tmp / f"{anahtar}.xml").write_text(rss(ad, ogeler), encoding="utf-8")
    bolgeler = {}
    for anahtar, (ad, bolge, dil, _) in feeds.items():
        bolgeler.setdefault(bolge, []).append(
            f'    - {{ad: {ad}, tur: x, dil: {dil}, yontem: rss, url: "file://{tmp.as_posix()}/{anahtar}.xml"}}')
    for b, satirlar in bolgeler.items():
        src += [f"  {b}:"] + satirlar
    (tmp / "sources.yaml").write_text("\n".join(src), encoding="utf-8")

    ayar = Ayarlar(kaynak_dosyasi=tmp / "sources.yaml", veritabani=tmp / "t.db", cikti_klasoru=tmp / "out")
    return tmp, ayar


def calistir():
    tmp, ayar = ortam_kur()

    # 1) Claude'suz tur
    ana.tur(ayar, client=False, gom=False, bot=False)
    con = db.baglan(ayar.veritabani)
    olaylar = con.execute("SELECT id, haber_sayisi, kaynak_sayisi FROM olay WHERE birlesti IS NULL AND haber_sayisi>0").fetchall()
    gruplar = {o["id"]: [r["baslik"][:40] for r in con.execute("SELECT baslik FROM haber WHERE olay_id=?", (o["id"],))] for o in olaylar}
    for oid, b in gruplar.items():
        print(oid, b)
    boyutlar = sorted(len(v) for v in gruplar.values())
    assert boyutlar == [1, 1, 2, 2, 2], f"beklenmeyen gruplama: {boyutlar}"

    # 2) Aynı beslemeler tekrar: yeni haber eklenmemeli
    ana.tur(ayar, client=False, gom=False, bot=False)
    assert con.execute("SELECT COUNT(*) FROM haber").fetchone()[0] == 8

    # 3) Sahte Claude ile: birleştirme + özet yolu
    con.execute("DELETE FROM haber"); con.execute("DELETE FROM olay"); con.commit()
    sahte = SahteClaude()
    ana.tur(ayar, client=sahte, gom=False, bot=False)
    iran = con.execute("SELECT o.* FROM olay o JOIN haber h ON h.olay_id=o.id WHERE h.baslik LIKE '%UAEA%'").fetchone()
    assert iran["haber_sayisi"] == 3 and iran["tr_ozet"] == "Test özeti.", dict(iran)
    for c in sahte.cagrilar:
        assert c["output_config"]["format"]["type"] == "json_schema" and c["fallbacks"] == "default"

    # 4) Anahtarsız: Türkçe İran haberi gömme modeliyle İngilizce olaya katılmalı, başlık Türkçe seçilmeli
    con.execute("DELETE FROM haber"); con.execute("DELETE FROM olay"); con.commit()
    ana.tur(ayar, client=False, gom=sahte_gomucu, bot=False)
    iran = con.execute("SELECT o.* FROM olay o JOIN haber h ON h.olay_id=o.id WHERE h.baslik LIKE '%UAEA%'").fetchone()
    assert iran["haber_sayisi"] == 3 and iran["tr_ozet"] is None, dict(iran)
    olay_sayisi = con.execute("SELECT COUNT(*) FROM olay WHERE birlesti IS NULL AND haber_sayisi>0").fetchone()[0]
    assert olay_sayisi == 4, olay_sayisi
    veri = json.loads((tmp / "out" / "events.json").read_text(encoding="utf-8"))
    iran_json = next(o for o in veri["olaylar"] if o["id"] == iran["id"])
    assert "UAEA" in iran_json["baslik"], iran_json["baslik"]

    veri = json.loads((tmp / "out" / "events.json").read_text(encoding="utf-8"))
    assert veri["olaylar"][0]["kaynaklar"], "olayın kaynak listesi boş"
    print((tmp / "out" / "son_olaylar.md").read_text(encoding="utf-8")[:1200])
    print(f"TAMAM · {len(sahte.cagrilar)} sahte Claude çağrısı · çıktı: {tmp}/out")


# ---------------------------------------------------------------------------------------------
# Aşağıdaki testler data/dipwatch.db'de bulunan gerçek veri kalitesi sorunlarının (bkz.
# prompts/veri-kalitesi.md) regresyon testleridir. Başlıklar gerçek haberlerden alınmıştır.
# ---------------------------------------------------------------------------------------------

def test_bolge_tahmini_icerikten():
    """Bölge kaynağın bölgesinden değil, başlıktaki ülke/şehir adlarından çıkarılmalı.
    Gerçek örnek: 'UK PM Burnham's Labour...' kaynağın bölgesi (kuresel/asya_pasifik) yüzünden
    Orta Doğu'ya düşüyordu; Japon-Fransız kimya Nobeli Asya-Pasifik'e düşüyordu."""
    from collector import bolge

    burnham = [
        {"kaynak": "Reuters", "bolge": "kuresel",
         "baslik": "UK PM Burnham's Labour fends off left-wing Greens in London", "ozet": None},
        {"kaynak": "The Hindu International", "bolge": "asya_pasifik",
         "baslik": "U.K. PM Burnham's Labour fends off left-wing Greens in local election", "ozet": None},
        {"kaynak": "Daily Sabah", "bolge": "orta_dogu",
         "baslik": "Burnham's Labour holds off Greens in London election test", "ozet": None},
    ]
    assert bolge.tahmin_et(burnham) == "avrupa", bolge.tahmin_et(burnham)

    kimya_nobeli = [{"kaynak": "The Japan Times", "bolge": "asya_pasifik",
                      "baslik": "Japanese scientist Kenso Soai and France's Henri B. Kagan win Nobel Prize "
                                "in chemistry", "ozet": None}]
    assert bolge.tahmin_et(kimya_nobeli) == "kuresel", bolge.tahmin_et(kimya_nobeli)

    baris_nobeli = [{"kaynak": "DW English", "bolge": "kuresel",
                      "baslik": "Nobel Peace Prize 2026 goes to Navanethem 'Navi' Pillay for her efforts "
                                "to promote peace and international law", "ozet": None}]
    assert bolge.tahmin_et(baris_nobeli) == "kuresel", bolge.tahmin_et(baris_nobeli)

    # Coğrafi işaret hiç yoksa da (Nobel/BM dışı, soyut bir konu) kuresel'e düşmeli
    assert bolge.tahmin_et([{"kaynak": "Foreign Policy", "bolge": "analiz_ve_resmi",
                              "baslik": "Diplomacy in an age of distrust", "ozet": None}]) == "kuresel"
    print("TAMAM · bölge tahmini içerikten çıkarılıyor")


def test_nobel_kalip_baslik_ayrisir():
    """Kalıp başlıklar ('... Ödülü sahibini buldu') ayırt edici terim (laureat adı) ağırlığıyla
    ayrışmalı: Nobel Edebiyat haberi Nobel Barış olayına girmemeli (gerçek örnek: olay 1038/995
    Kimya Nobeli TR/EN ayrı kalmıştı, ama Edebiyat/Barış kalıpları da hiç karışmamalı)."""
    import sqlite3

    from collector import cluster, db
    from collector.config import Ayarlar

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SEMA)
    g = cluster.Gruplayici(con, Ayarlar())

    edebiyat_oid, yeni1 = g.ata({"baslik": "2026 Nobel Edebiyat Ödülü sahibini buldu: Anne Carson",
                                 "ozet": "", "yayin": "2026-10-01T00:00:00+00:00"})
    assert yeni1
    baris_oid, yeni2 = g.ata({"baslik": "2026 Nobel Barış Ödülü sahibini buldu: Navi Pillay",
                              "ozet": "", "yayin": "2026-10-02T00:00:00+00:00"})
    assert yeni2, "Nobel Edebiyat ve Nobel Barış kalıp başlığı yüzünden yanlışlıkla aynı olaya girdi"
    assert edebiyat_oid != baris_oid

    # Aynı dilde, aynı laureat adını taşıyan başka bir başlık doğru kümeye katılmalı (TF-IDF yalnızca
    # aynı dildeki haberi eşleştirir; diller arası birleştirme embed.py/summarize.birlestir() işi)
    baris_oid2, yeni3 = g.ata({"baslik": "Navi Pillay, Nobel Barış Ödülü'ne layık görüldü",
                               "ozet": "", "yayin": "2026-10-02T01:00:00+00:00"})
    assert not yeni3 and baris_oid2 == baris_oid
    print("TAMAM · Nobel Edebiyat/Barış kalıp başlıkları ayırt edici terimlerle ayrışıyor")


def test_gecersiz_baslik_filtrelenir():
    """'Careers at Arab News' / 'JEDDAH/RIYADH: ARAB NEWS TEAM' gibi haber olmayan künye/kurumsal
    sayfalar fetch aşamasında elenmeli (gerçek örnek: Arab News'in Google News üzerinden çekilen
    bu iki satırı bir olaya dönüşüp zamanla Husi saldırısı haberlerini de içine çekmişti)."""
    from collector.config import Kaynak
    from collector.fetch import cek

    ogeler = [
        ("Careers at Arab News", "", 1),
        ("JEDDAH/RIYADH: ARAB NEWS TEAM", "", 1),
        ("Arab League, UN condemn Houthi attacks on Saudi Arabia", "Gerçek bir haber.", 1),
    ]
    tmp = Path(tempfile.mkdtemp())
    (tmp / "feed.xml").write_text(rss("Arab News", ogeler), encoding="utf-8")
    k = Kaynak(ad="Arab News", bolge="orta_dogu", url=f"file://{tmp.as_posix()}/feed.xml")
    _, haberler, hata = cek(k)
    assert hata is None
    assert [h["baslik"] for h in haberler] == ["Arab League, UN condemn Houthi attacks on Saudi Arabia"], haberler
    print("TAMAM · haber olmayan künye/kurumsal başlıklar fetch'te elendi")


def test_ayni_kaynak_baslik_tekrari_filtrelenir():
    """Aynı kaynaktan normalize edilmiş aynı başlık tek haber sayılmalı (gerçek örnek: Middle East
    Eye'ın Google News üzerinden aynı makaleyi farklı yönlendirme kimlikleriyle iki kez vermesi,
    veritabanında aynı başlıkla iki ayrı satır olarak kalmıştı)."""
    FEEDS_TEK = {"mee": ("Middle East Eye", "orta_dogu", "en", [
        ("EU warns of Houthi threat deeper inside Saudi Arabia after Riyadh attack",
         "AB uyarısı.", 1),
    ])}
    tmp, ayar = ortam_kur(FEEDS_TEK)
    ana.tur(ayar, client=False, gom=False, bot=False)
    con = db.baglan(ayar.veritabani)
    assert con.execute("SELECT COUNT(*) FROM haber").fetchone()[0] == 1

    # İkinci "tur": Google News'in aynı haberi farklı bir yönlendirme linkiyle tekrar döndürdüğünü simüle et
    (tmp / "mee.xml").write_text(rss("Middle East Eye", [
        ("EU warns of Houthi threat deeper inside Saudi Arabia after Riyadh attack",
         "AB uyarısı.", 1),
    ]).replace("mee/0", "mee/farkli-yonlendirme-kimligi"), encoding="utf-8")
    ana.tur(ayar, client=False, gom=False, bot=False)
    n = con.execute("SELECT COUNT(*) FROM haber").fetchone()[0]
    assert n == 1, f"aynı kaynaktan aynı başlık tekrar eklendi: {n} satır"
    print("TAMAM · aynı kaynak + aynı başlık tekrarı (farklı link) ikinci kez eklenmedi")


def test_baslik_sec_merkeze_yakin():
    """Claude özeti yoksa başlık, kümenin merkez vektörüne en yakın başlık olmalı (en son Türkçe
    başlık değil); 'Explainer'/'... - live'/'analysis' kalıp başlıkları seçilmemeli."""
    import numpy as np

    from collector.export import _baslik_sec

    def v(x, y):
        a = np.array([x, y], dtype=np.float32)
        return (a / np.linalg.norm(a)).tobytes()

    haberler = [
        {"baslik": "Explainer: what the chemistry Nobel means", "dil": "en", "vektor": v(0.2, 1.0)},
        {"baslik": "Kagan, Soai win Nobel chemistry prize for solving chemical asymmetry puzzle",
         "dil": "en", "vektor": v(1.0, 0.05)},
        {"baslik": "French-Japanese duo wins 2026 Nobel chemistry prize", "dil": "en", "vektor": v(0.95, 0.1)},
        {"baslik": "2026 Nobel Kimya Ödülü'nün sahipleri belli oldu", "dil": "tr", "vektor": v(0.9, 0.08)},
    ]
    secilen = _baslik_sec(haberler)
    assert secilen != haberler[0]["baslik"], "açıklayıcı (Explainer) kalıp başlık seçildi"
    assert secilen == haberler[3]["baslik"], (
        "merkeze en yakın adaylar arasında Türkçe tercih edilmedi: " + secilen)

    # Vektör yoksa (fastembed hiç çalışmamışsa) eski davranışa (en son Türkçe) düşmeli
    haberler_vektorsuz = [{"baslik": "English first", "dil": "en", "vektor": None},
                          {"baslik": "Türkçe ilk", "dil": "tr", "vektor": None},
                          {"baslik": "Türkçe son", "dil": "tr", "vektor": None}]
    assert _baslik_sec(haberler_vektorsuz) == "Türkçe son"
    print("TAMAM · başlık seçimi merkeze yakınlığa göre, kalıp başlıklar hariç")


def test_icerik_turu_ayrı_olay_acmaz():
    """'Explainer'/'analysis'/'... - live' başlıklı haberler olaya bağlı kalmalı (tür etiketi
    taşıyarak) ama tek başlarına yeni bir olay açmamalı: cluster.py'de bu tür için eşik gevşetilir."""
    import sqlite3

    from collector import cluster, db
    from collector.config import Ayarlar

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SEMA)
    g = cluster.Gruplayici(con, Ayarlar())

    # Gerçekçi bir idf arka planı olmadan (iki belgelik bir "derlemde") paylaşılan tek kelimenin
    # (Houthi) idf'i dejenere biçimde sıfıra düşer; önce birkaç ilgisiz dolgu haberle normal bir
    # derlem oluştur (gerçek üründe idf_penceresi_saat=72 saatlik tüm haberlerden hesaplanır).
    for i, baslik in enumerate([
            "Markets rally as central bank holds interest rates steady",
            "Heavy rainfall triggers flooding across southern provinces",
            "Tech giant unveils new smartphone with improved battery life",
            "Local election turnout hits record high in coastal region",
            "Scientists discover new species of deep sea fish"]):
        g.ata({"baslik": baslik, "ozet": "", "yayin": f"2026-10-09T0{i}:00:00+00:00",
               "icerik_turu": "haber"})

    oid, yeni = g.ata({"baslik": "Saudi-led coalition vows response against Houthi attacks on airports",
                       "ozet": "Riyad ve Abha havalimanlarına saldırı sonrası.",
                       "yayin": "2026-10-09T08:00:00+00:00", "icerik_turu": "haber"})
    assert yeni

    # "analiz" etiketli bir yazı, normal eşikte (0.28) kalan ama gevşetilmiş eşikte (0.14) olaya giren
    oid2, yeni2 = g.ata({"baslik": "Analysis: why Houthi attacks on Saudi airports are escalating "
                                   "the regional conflict",
                        "ozet": "", "yayin": "2026-10-09T09:00:00+00:00", "icerik_turu": "analiz"})
    assert not yeni2 and oid2 == oid, "analiz etiketli başlık mevcut olaya bağlanmadı, kendi olayını açtı"
    print("TAMAM · analiz/canlı etiketli başlıklar tek başına olay açmıyor")


def test_db_kilidi_eszamanli_calismayi_onler():
    """`yeniden-grupla` ile `dongu`/`tur` aynı veritabanında eşzamanlı çalışırsa birbirinin olay_id
    atamalarının üzerine yazabilir (adversarial review bulgusu). `tur()` artık bir dosya kilidi
    tutuyor: kilit zaten tutuluyorsa hemen hata vermeli, kendi işi bitince kilidi bırakmalı."""
    tmp, ayar = ortam_kur()
    kilit_yolu = ayar.veritabani.with_name(ayar.veritabani.name + ".lock")
    kilit_yolu.write_text("99999", encoding="utf-8")
    try:
        try:
            ana.tur(ayar, client=False, gom=False, bot=False)
            raise AssertionError("kilit tutulurken tur() çalışmaya izin verdi")
        except RuntimeError:
            pass
    finally:
        kilit_yolu.unlink(missing_ok=True)

    ana.tur(ayar, client=False, gom=False, bot=False)
    assert not kilit_yolu.exists(), "tur() bittikten sonra kilit dosyası kalmamalı"
    print("TAMAM · dosya kilidi, yeniden-grupla ile tur/dongu'nun eşzamanlı çalışmasını engelliyor")


def test_telegram_gecisleri_uygula_yeniden_gruplama_sonrasi():
    """yeniden-grupla önceden bildirilmiş olayları birleştirirse (ya da başka bir olaya taşırsa),
    bildirim takibi köke göre tek kayda inmeli ve kaynak_sayisi tabanı GÜNCEL sayıya sıfırlanmalı --
    aksi halde bir sonraki dongu turu bu sıçramayı organik "olay büyüyor" sanıp sahte bildirim
    gönderir (adversarial review bulgusu)."""
    import sqlite3

    from collector import db, telegram

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SEMA)
    con.executescript(telegram.SEMA)

    # Eski durum: olay 1 ve olay 2 ayrı ayrı bildirilmiş (biri mesaj_id'li, biri değil)
    con.execute("INSERT INTO olay (id, haber_sayisi, kaynak_sayisi) VALUES (1, 3, 3)")
    con.execute("INSERT INTO olay (id, haber_sayisi, kaynak_sayisi) VALUES (2, 2, 2)")
    con.execute("INSERT INTO bildirim (olay_id, kaynak_sayisi, mesaj_id, zaman) VALUES (1, 3, 111, 't1')")
    con.execute("INSERT INTO bildirim (olay_id, kaynak_sayisi, mesaj_id, zaman) VALUES (2, 2, NULL, 't2')")
    # yeniden-grupla sonrası: ikisinin içeriği de yeni olay 10'da birleşmiş, 10 kaynaklı olmuş
    con.execute("INSERT INTO olay (id, haber_sayisi, kaynak_sayisi) VALUES (10, 5, 10)")
    con.commit()

    tasinan = telegram.gecisleri_uygula(con, {1: 10, 2: 10})
    assert tasinan == 1

    kalan = [dict(r) for r in con.execute("SELECT * FROM bildirim")]
    assert len(kalan) == 1, f"birleşen olaylar tek bildirim kaydına inmedi: {kalan}"
    assert kalan[0]["olay_id"] == 10
    assert kalan[0]["kaynak_sayisi"] == 10, "taban, kökün güncel kaynak sayısına sıfırlanmadı"
    assert kalan[0]["mesaj_id"] == 111, "zaten mesajı gönderilmiş (mesaj_id'li) kayıt tercih edilmedi"
    print("TAMAM · yeniden-grupla sonrası Telegram bildirim takibi senkronlanıyor")


def test_embed_periyodik_birlestirme():
    """embed.birlestirme_onerileri yalnızca 'acilan' (bu turda yeni açılan) olaylara değil, TÜM aktif
    olaylara bakmalı: aksi halde aynı olayın günler sonra başka dilde/kaynaktan açılan hali bir daha
    hiç karşılaştırılmaz (gerçek örnek: Kimya Nobeli TR/EN olayları, Trump'ın ödülü hak ettiğini
    söylediği üç ayrı haber hiç karşılaştırılmadığı için birleşmemişti)."""
    import sqlite3

    import numpy as np

    from collector import db, embed
    from collector.config import Ayarlar

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(db.SEMA)
    simdi = "2026-10-09T12:00:00+00:00"

    def olay_ekle(oid, kaynak_sayisi, vektorler):
        con.execute("INSERT INTO olay (id, guncelleme, haber_sayisi, kaynak_sayisi) VALUES (?,?,?,?)",
                    (oid, simdi, len(vektorler), kaynak_sayisi))
        for i, v in enumerate(vektorler):
            con.execute("INSERT INTO haber (olay_id, kaynak, baslik, vektor) VALUES (?,?,?,?)",
                        (oid, f"k{oid}_{i}", f"b{oid}_{i}", v.astype(np.float32).tobytes()))

    # A ve B birbirine çok yakın (aynı somut gelişme), ama ikisi de "bu turda yeni açılan" değil
    olay_ekle(1, kaynak_sayisi=5, vektorler=[np.array([1.0, 0.0, 0.0])])
    olay_ekle(2, kaynak_sayisi=1, vektorler=[np.array([0.98, 0.2, 0.0])])
    # C tamamen ilgisiz bir olay
    olay_ekle(3, kaynak_sayisi=3, vektorler=[np.array([0.0, 0.0, 1.0])])
    con.commit()
    ayar = Ayarlar()

    # "acilan" boşsa (bu turda hiç yeni olay açılmadıysa) eski kod hiçbir şey önermezdi
    assert embed.birlestirme_onerileri(con, ayar, []) == []
    # Periyodik (adaylar=None): tüm aktif olaylar yeniden değerlendirilir, A-B eşleşmesi bulunur
    oneriler = embed.birlestirme_onerileri(con, ayar, None)
    assert oneriler == [(2, 1)], oneriler  # zayıf (az kaynaklı) olan önce: B(1 kaynak) -> A(5 kaynak)
    print("TAMAM · embed birleştirmesi artık tüm aktif olayları periyodik olarak yeniden değerlendiriyor")


if __name__ == "__main__":
    calistir()
    test_bolge_tahmini_icerikten()
    test_nobel_kalip_baslik_ayrisir()
    test_gecersiz_baslik_filtrelenir()
    test_ayni_kaynak_baslik_tekrari_filtrelenir()
    test_baslik_sec_merkeze_yakin()
    test_icerik_turu_ayrı_olay_acmaz()
    test_embed_periyodik_birlestirme()
    test_db_kilidi_eszamanli_calismayi_onler()
    test_telegram_gecisleri_uygula_yeniden_gruplama_sonrasi()
