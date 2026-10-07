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


def calistir():
    tmp = Path(tempfile.mkdtemp())
    src = ["bolgeler:"]
    for anahtar, (ad, bolge, dil, ogeler) in FEEDS.items():
        (tmp / f"{anahtar}.xml").write_text(rss(ad, ogeler), encoding="utf-8")
    bolgeler = {}
    for anahtar, (ad, bolge, dil, _) in FEEDS.items():
        bolgeler.setdefault(bolge, []).append(
            f'    - {{ad: {ad}, tur: x, dil: {dil}, yontem: rss, url: "file://{tmp}/{anahtar}.xml"}}')
    for b, satirlar in bolgeler.items():
        src += [f"  {b}:"] + satirlar
    (tmp / "sources.yaml").write_text("\n".join(src), encoding="utf-8")

    ayar = Ayarlar(kaynak_dosyasi=tmp / "sources.yaml", veritabani=tmp / "t.db", cikti_klasoru=tmp / "out")

    # 1) Claude'suz tur
    ana.tur(ayar, client=False)
    con = db.baglan(ayar.veritabani)
    olaylar = con.execute("SELECT id, haber_sayisi, kaynak_sayisi FROM olay WHERE birlesti IS NULL AND haber_sayisi>0").fetchall()
    gruplar = {o["id"]: [r["baslik"][:40] for r in con.execute("SELECT baslik FROM haber WHERE olay_id=?", (o["id"],))] for o in olaylar}
    for oid, b in gruplar.items():
        print(oid, b)
    boyutlar = sorted(len(v) for v in gruplar.values())
    assert boyutlar == [1, 1, 2, 2, 2], f"beklenmeyen gruplama: {boyutlar}"

    # 2) Aynı beslemeler tekrar: yeni haber eklenmemeli
    ana.tur(ayar, client=False)
    assert con.execute("SELECT COUNT(*) FROM haber").fetchone()[0] == 8

    # 3) Sahte Claude ile: birleştirme + özet yolu
    con.execute("DELETE FROM haber"); con.execute("DELETE FROM olay"); con.commit()
    sahte = SahteClaude()
    ana.tur(ayar, client=sahte)
    iran = con.execute("SELECT o.* FROM olay o JOIN haber h ON h.olay_id=o.id WHERE h.baslik LIKE '%UAEA%'").fetchone()
    assert iran["haber_sayisi"] == 3 and iran["tr_ozet"] == "Test özeti.", dict(iran)
    for c in sahte.cagrilar:
        assert c["output_config"]["format"]["type"] == "json_schema" and c["fallbacks"] == "default"

    veri = json.loads((tmp / "out" / "events.json").read_text(encoding="utf-8"))
    assert veri["olaylar"][0]["kaynaklar"], "olayın kaynak listesi boş"
    print((tmp / "out" / "son_olaylar.md").read_text(encoding="utf-8")[:1200])
    print(f"TAMAM · {len(sahte.cagrilar)} sahte Claude çağrısı · çıktı: {tmp}/out")


if __name__ == "__main__":
    calistir()
