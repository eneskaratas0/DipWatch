"""Teknoloji ve siber güvenlik bölümünün ağsız testi: sahte RSS ve HTML dosyaları (file://).

Çalıştırma:  python3 -m tests.test_teknoloji
Haber içerikleri test için uydurulmuştur.
"""
import json
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from collector import db
from teknoloji import kazi, toplayici
from web.teknoloji import yaz

SIMDI = datetime.now(timezone.utc)


def rss(ad, ogeler):
    """ogeler: (link_sonu, başlık, açıklama, kaç_saat_önce, etiketler)"""
    items = "".join(
        f"<item><title>{t}</title><link>https://ornek.test/{ad}/{l}?utm_source=rss</link>"
        f"<description>{d}</description><pubDate>{format_datetime(SIMDI - timedelta(hours=h))}</pubDate>"
        + "".join(f"<category>{c}</category>" for c in etiketler) + "</item>"
        for l, t, d, h, etiketler in ogeler)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{ad}</title>{items}</channel></rss>'


KAZI_HTML = f"""<html><body><nav><a href="/news-events/alerts/menu">Alerts</a></nav>
<div class="c"><time datetime="{(SIMDI - timedelta(hours=3)).isoformat()}">bugün</time>
  <a href="/news-events/alerts/ics-acme-plc">ACME PLC firmware vulnerabilities allow remote code execution</a></div>
<div class="c"><a href="/news-events/alerts/kev-ekleme">CISA Adds Three Known Exploited Vulnerabilities to Catalog</a>
  <time datetime="{(SIMDI - timedelta(hours=5)).isoformat()}">dün</time></div>
<a href="/hakkimizda">About us page with many words here</a></body></html>"""


def kur(tmp: Path):
    (tmp / "thn.xml").write_text(rss("thn", [
        ("1", "Hackers Exploited Cisco SD-WAN Flaw to Plant Malware Built to Steal Encryption Keys",
         "Threat actors exploited a Cisco SD-WAN flaw. The post Hackers... appeared first on THN.", 6, []),
        ("2", "Oracle E-Business Suite RCE Flaw Targeted Days After Security Patch", "Oracle flaw.", 4, []),
        ("eski", "Very old story about a botnet takedown long ago", "Eski.", 24 * 60, []),
    ]), encoding="utf-8")
    (tmp / "bc.xml").write_text(rss("bc", [
        # aynı olay, başka kaynak, farklı kelimeler -> tekrar (THN'nin haberine "Ayrıca" olarak eklenmeli)
        ("a", "Hackers exploit Cisco SD-WAN flaw to deploy custom KeyDrift malware", "Cisco SD-WAN.", 2, ["Security"]),
        # aynı başlık, başka kaynak -> tekrar
        ("b", "Oracle E-Business Suite RCE Flaw Targeted Days After Security Patch", "Aynı başlık.", 1, ["Security"]),
        # etiketsiz kelime eşleşmesine bakılmaz: etiketi Microsoft -> teknoloji
        ("c", "Microsoft fixes Remote Desktop failures caused by recent Windows updates",
         "The security update broke RDP.", 3, ["Microsoft"]),
        ("d", "<b>Chrome</b> extensions with 13 million installs caught hijacking searches " + "x" * 10,
         "Uzun özet " + "kelime " * 80 + "[...]", 1, ["Security"]),
    ]), encoding="utf-8")
    (tmp / "krebs.xml").write_text(rss("krebs", [
        # yalnızca genel kelimeleri (patch, security, flaw) paylaşıyor -> tekrar SAYILMAMALI
        ("1", "Microsoft Patches More Than 1,400 Security Flaws", "Patch Tuesday.", 5, []),
    ]), encoding="utf-8")
    (tmp / "ars.xml").write_text(rss("ars", [
        ("1", "Trump declares robot imports a national security threat", "Tariffs.", 7, []),  # etiketsiz -> kelime
        ("2", "Massive leak exposes 41,000 DHS workers", "Leak.", 8, []),
    ]), encoding="utf-8")
    (tmp / "cisa.html").write_text(KAZI_HTML, encoding="utf-8")
    t = tmp.as_posix()
    (tmp / "kaynaklar.yaml").write_text(f"""kaynaklar:
  - {{ad: The Hacker News, kategori: siber_guvenlik, url: "file://{t}/thn.xml"}}
  - {{ad: BleepingComputer, kategori: otomatik, url: "file://{t}/bc.xml"}}
  - {{ad: Krebs on Security, kategori: siber_guvenlik, url: "file://{t}/krebs.xml"}}
  - {{ad: Ars Technica, kategori: otomatik, url: "file://{t}/ars.xml"}}
  - ad: CISA
    kategori: siber_guvenlik
    url: "file://{t}/yok.xml"
    yedekler:
      - {{yontem: kazi, url: "file://{t}/cisa.html", link_deseni: "/news-events/alerts/[^/?#]+$"}}
  - {{ad: Kapalı, kategori: teknoloji, url: "file://{t}/yok.xml", durum: kapali}}
""", encoding="utf-8")


def test_kazi_ayristir():
    sonuc = kazi.ayristir(KAZI_HTML, "https://www.cisa.gov/news-events/alerts", "/news-events/alerts/[^/?#]+$")
    linkler = [h["link"] for h in sonuc]
    assert linkler == ["https://www.cisa.gov/news-events/alerts/ics-acme-plc",
                       "https://www.cisa.gov/news-events/alerts/kev-ekleme"], linkler  # "Alerts" menü linki kısa
    assert all(h["yayin"] for h in sonuc)
    assert sonuc[0]["yayin"] > sonuc[1]["yayin"]  # tarih, linkin önündeki/arkasındaki <time>'dan


def test_ozet_ve_kategori():
    assert toplayici.ozet_kisalt("Kısa. The post X appeared first on Y.") == "Kısa."
    uzun = toplayici.ozet_kisalt("kelime " * 100, 50)
    assert uzun.endswith("…") and len(uzun) <= 51
    k = toplayici.TeknoKaynak(ad="x", kategori="otomatik", url="")
    assert toplayici.kategori_belirle(k, "New ransomware gang hits hospitals", "") == "siber_guvenlik"
    assert toplayici.kategori_belirle(k, "Apple unveils new MacBook", "") == "teknoloji"
    assert toplayici.kategori_belirle(k, "Trump calls robots a national security threat", "") == "teknoloji"
    assert toplayici.kategori_belirle(k, "Patch it", "security", ["Microsoft"]) == "teknoloji"


def calistir():
    test_kazi_ayristir()
    test_ozet_ve_kategori()

    tmp = Path(tempfile.mkdtemp())
    kur(tmp)
    ayar = toplayici.Ayar(kaynak_dosyasi=tmp / "kaynaklar.yaml")
    con = db.baglan(tmp / "dipwatch.db")
    cikti = tmp / "teknoloji.json"
    s = toplayici.tur(con, ayar, cikti)
    assert s["kaynak"] == 5 and s["calisan"] == 5, s  # kapalı kaynak atlanır; CISA RSS'i yok -> kazıma
    assert s["tekrar"] == 2, s
    durum = {r["ad"]: r["yontem"] for r in con.execute("SELECT ad, yontem FROM tekno_kaynak_durum")}
    assert durum["CISA"] == "kazi" and durum["Ars Technica"] == "rss", durum

    veri = json.loads(cikti.read_text(encoding="utf-8"))
    h = veri["haberler"]
    basliklar = [x["baslik"] for x in h]
    assert [x["yayin"] for x in h] == sorted((x["yayin"] for x in h), reverse=True), "en yeni en üstte değil"
    assert "Very old story about a botnet takedown long ago" not in basliklar  # 60 günlük haber eklenmez
    assert sum("Cisco SD-WAN" in b for b in basliklar) == 1, basliklar
    assert basliklar.count("Oracle E-Business Suite RCE Flaw Targeted Days After Security Patch") == 1
    assert "Microsoft Patches More Than 1,400 Security Flaws" in basliklar, "genel kelimeler tekrar sayıldı"
    cisco = next(x for x in h if "Cisco SD-WAN" in x["baslik"])
    assert cisco["kaynak"] == "The Hacker News"  # ilk yayımlayan asıl kaynak
    assert [d["kaynak"] for d in cisco["diger_kaynaklar"]] == ["BleepingComputer"]
    for x in h:
        assert set(x) >= {"baslik", "kaynak", "yayin", "link", "ozet", "kategori"}
        assert "utm_source" not in x["link"]
    def kat(bas):
        return next(x["kategori"] for x in h if x["baslik"].startswith(bas))
    assert kat("Microsoft fixes Remote") == "teknoloji"  # etiketi "Microsoft"
    assert kat("Trump declares robot") == "teknoloji"   # "national security" siber sayılmaz
    assert kat("Massive leak exposes") == "siber_guvenlik"
    assert kat("ACME PLC firmware") == "siber_guvenlik"  # kazıma ile gelen CISA haberi
    chrome = next(x for x in h if x["baslik"].startswith("Chrome"))
    assert "<b>" not in chrome["baslik"] and chrome["ozet"].endswith("…")

    # İkinci tur: aynı beslemeler -> hiçbir şey yeniden eklenmez, tekrarlar da yeniden sayılmaz
    s2 = toplayici.tur(con, ayar, cikti)
    assert s2["yeni"] == 0 and s2["tekrar"] == 0, s2
    assert len(json.loads(cikti.read_text(encoding="utf-8"))["haberler"]) == len(h)

    # Site sayfası: filtreler, kaçışlama, "Ayrıca" satırı
    (tmp / "zararli.json").write_text(json.dumps({"olusturulma": SIMDI.isoformat(), "haberler": h + [
        {"id": 999, "baslik": "<script>alert(1)</script>", "kaynak": "X", "yayin": SIMDI.isoformat(),
         "link": "javascript:alert(1)", "ozet": "", "kategori": "teknoloji", "diger_kaynaklar": []}]}), encoding="utf-8")
    site = tmp / "public"
    assert yaz(tmp / "zararli.json", site) == len(h) + 1
    sayfa = (site / "teknoloji.html").read_text(encoding="utf-8")
    assert 'data-kategori="siber_guvenlik"' in sayfa and 'id="tekno-kaynak"' in sayfa
    assert '<option value="CISA">' in sayfa and "Ayrıca:" in sayfa
    assert "<script>alert" not in sayfa and 'href="javascript:' not in sayfa
    assert 'aria-current="page"' in sayfa and (site / "filtre.js").exists()
    # Veri yoksa da sayfa oluşur (menüdeki link kırılmasın)
    assert yaz(tmp / "olmayan.json", tmp / "bos") == 0
    assert "Henüz teknoloji haberi" in (tmp / "bos" / "teknoloji.html").read_text(encoding="utf-8")
    print(f"TAMAM · {len(h)} haber · çıktı: {site}")


if __name__ == "__main__":
    calistir()
