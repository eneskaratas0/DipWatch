"""Site üreticisinin ağsız testi: küçük bir events.json'dan site üretir ve sayfaları kontrol eder.

Çalıştırma:  python3 -m tests.test_web
Olaylar test için uydurulmuştur.
"""
import json
import tempfile
from pathlib import Path

from web.build import olustur

OLAYLAR = [
    {"id": 1, "baslik": "İran ile UAEA Viyana'da nükleer denetimleri görüştü", "ozet": "Taraflar denetimlerin yeniden başlaması için görüştü.",
     "turkce_ozet_var": True, "bolge": "orta_dogu", "ulkeler": ["İran"], "etiketler": ["nükleer"], "onem": 3,
     "ilk_haber": "2026-10-06T21:30:00+00:00", "son_haber": "2026-10-07T09:00:00+00:00", "kaynak_sayisi": 2,
     "kaynaklar": [
         {"kaynak": "BBC World", "baslik": "Iran and IAEA hold talks", "link": "https://ornek.test/bbc/1", "dil": "en", "yayin": "2026-10-06T21:30:00+00:00"},
         {"kaynak": "Anadolu Ajansı", "baslik": "İran ile UAEA görüştü", "link": "https://ornek.test/aa/1", "dil": "tr", "yayin": "2026-10-07T09:00:00+00:00"},
     ]},
    {"id": 2, "baslik": "<script>alert(1)</script> başlık", "ozet": None, "turkce_ozet_var": False, "bolge": "afrika",
     "ulkeler": [], "etiketler": [], "onem": None,
     "ilk_haber": "2026-10-05T10:00:00+00:00", "son_haber": "2026-10-05T10:00:00+00:00", "kaynak_sayisi": 1,
     "kaynaklar": [{"kaynak": "X", "baslik": "kötü link", "link": "javascript:alert(1)", "dil": "en", "yayin": "2026-10-05T10:00:00+00:00"}]},
]


def calistir():
    tmp = Path(tempfile.mkdtemp())
    girdi = tmp / "events.json"
    girdi.write_text(json.dumps({"olusturulma": "2026-10-07T10:00:00+00:00", "olaylar": OLAYLAR}, ensure_ascii=False), encoding="utf-8")
    cikti = tmp / "public"
    (cikti / "olay").mkdir(parents=True)
    (cikti / "olay" / "999.html").write_text("eski")  # süresi dolmuş olay sayfası silinmeli

    assert olustur(girdi, cikti) == 2
    index = (cikti / "index.html").read_text(encoding="utf-8")
    # olay 1 (2 kaynaklı) ana sayfada; olay 2 (tek kaynaklı) performans için arşive taşınır
    assert 'href="olay/1.html"' in index and "7 Ekim 2026, Çarşamba" in index
    assert 'href="olay/2.html"' not in index and "5 Ekim 2026, Pazartesi" not in index
    assert not (cikti / "olay" / "999.html").exists()

    tek = (cikti / "tek-kaynakli.html").read_text(encoding="utf-8")
    assert 'href="olay/2.html"' in tek and "5 Ekim 2026, Pazartesi" in tek and 'href="olay/1.html"' not in tek
    assert "<script>alert" not in tek, "başlık kaçışlanmamış"

    orta = (cikti / "bolge" / "orta_dogu.html").read_text(encoding="utf-8")
    assert "olay/1.html" in orta and "olay/2.html" not in orta
    assert (cikti / "bolge" / "turkiye.html").exists()  # boş bölgenin de sayfası olur
    assert (cikti / "bolge" / "turkiye-tek.html").exists()
    afrika_tek = (cikti / "bolge" / "afrika-tek.html").read_text(encoding="utf-8")
    assert "olay/2.html" in afrika_tek

    olay = (cikti / "olay" / "1.html").read_text(encoding="utf-8")
    assert "Taraflar denetimlerin" in olay and "Zaman çizelgesi" in olay
    assert olay.index("ornek.test/bbc/1") < olay.index("ornek.test/aa/1")  # zaman sırası
    assert "7 Ekim 00:30" in olay, "İstanbul saatine çevrilmemiş"  # 21:30 UTC = 00:30 TSİ
    assert 'href="../stil.css"' in olay

    kotu = (cikti / "olay" / "2.html").read_text(encoding="utf-8")
    assert "javascript:" not in kotu and "henüz Türkçe özet yok" in kotu
    print(f"TAMAM · çıktı: {cikti}")


if __name__ == "__main__":
    calistir()
