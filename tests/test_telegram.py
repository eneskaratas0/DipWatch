"""Telegram bildirimlerinin ağsız testi: sahte beslemeler + Telegram'a hiç bağlanmayan sahte bot.

Çalıştırma:  python3 -m tests.test_telegram
Haber içerikleri test için uydurulmuştur.
"""
from collector import __main__ as ana
from collector import db, telegram
from collector.telegram import Kurallar, eslesen_kelimeler, mesaj_metni, sadelestir
from tests.test_collector import FEEDS, ortam_kur


class SahteBot:
    def __init__(self, hata=False):
        self.mesajlar, self.hata = [], hata

    def gonder(self, metin, yanitlanan=None):
        if self.hata:
            raise RuntimeError("ağ yok")
        self.mesajlar.append((metin, yanitlanan))
        return 100 + len(self.mesajlar)


IRAN_EK = {
    f"ek{i}": (f"Ek Kaynak {i}", "orta_dogu", "en", [
        (f"Iran and IAEA hold talks in Vienna on nuclear inspections, report {i}",
         "Iranian officials met the UN nuclear watchdog in Vienna to discuss inspections.", 1)])
    for i in range(3)
}


def tur(feeds, db_yolu, bot, kurallar):
    _, ayar = ortam_kur(feeds)
    ayar.veritabani = db_yolu
    ana.tur(ayar, client=False, gom=False, bot=False)
    con = db.baglan(db_yolu)
    n = telegram.bildir(con, ayar, bot=bot, kurallar=kurallar, bekleme=0)
    con.close()
    return n


def birim_testleri():
    assert sadelestir("İRAN Şam Iraklı") == "iran sam irakli"
    olay = {"baslik": "Senator visits Gaza", "ozet": None, "ulkeler": [], "etiketler": [],
            "kaynaklar": [{"baslik": "Iranian talks"}]}
    assert eslesen_kelimeler(olay, ["NATO", "Gazze", "Gaza", "İran"]) == ["Gaza", "İran"]

    kotu = {"id": 7, "baslik": "<script>x</script> & co", "ozet": "a < b", "bolge": "afrika", "ulkeler": [],
            "etiketler": [], "onem": 4, "kaynak_sayisi": 2, "son_haber": "2026-10-07T09:00:00+00:00",
            "kaynaklar": [{"kaynak": "X", "baslik": "kötü", "link": "javascript:alert(1)", "yayin": "1"},
                          {"kaynak": "Y", "baslik": "iyi", "link": "https://ornek.test/a?b=1&c=2", "yayin": "2"}]}
    m = mesaj_metni(kotu, Kurallar(site_adresi="https://site.test/"))
    assert "<script>" not in m and "&lt;script&gt;" in m and "javascript:" not in m, m
    assert 'href="https://ornek.test/a?b=1&amp;c=2"' in m and "★★★★" in m and "Afrika" in m
    assert 'href="https://site.test/olay/7.html"' in m


def calistir():
    birim_testleri()
    db_yolu = ortam_kur({})[0] / "bildirim.db"
    kurallar = Kurallar(bolgeler=[], anahtar_kelimeler=["İran"], min_kaynak=2, buyume_esigi=3)
    bot = SahteBot()

    # 1) İlk çalıştırma: yalnızca "bildirimler açıldı" mesajı, mevcut olaylar görüldü sayılır
    assert tur({"bbc": FEEDS["bbc"]}, db_yolu, bot, kurallar) == 1
    assert "açıldı" in bot.mesajlar[0][0] and "0 olay" in bot.mesajlar[0][0], bot.mesajlar

    # 2) Al Jazeera aynı İran haberini verince olay 2 kaynağa çıkar: "Yeni olay". Sudan olayı da 2 kaynaklı ama
    #    anahtar kelimeye uymuyor, gönderilmemeli.
    assert tur({"bbc": FEEDS["bbc"], "aj": FEEDS["aj"]}, db_yolu, bot, kurallar) == 1
    metin, yanit = bot.mesajlar[1]
    assert "Yeni olay" in metin and "Iran and IAEA" in metin and "BBC World" in metin and "Al Jazeera" in metin, metin
    assert "El Fasher" not in metin and yanit is None
    ilk_mesaj_id = 102

    # 3) Değişiklik yoksa tekrar gönderilmez
    assert tur({"bbc": FEEDS["bbc"], "aj": FEEDS["aj"]}, db_yolu, bot, kurallar) == 0

    # 4) 3 yeni kaynak daha: "Olay büyüyor", ilk mesaja yanıt olarak
    assert tur({"bbc": FEEDS["bbc"], "aj": FEEDS["aj"], **IRAN_EK}, db_yolu, bot, kurallar) == 1
    metin, yanit = bot.mesajlar[2]
    assert "Olay büyüyor" in metin and "2 → 5 kaynak" in metin and yanit == ilk_mesaj_id, (metin, yanit)

    # 5) Gönderim hatası: kayıt düşülmez, sonraki turda yeniden denenir
    bolge_kurali = Kurallar(bolgeler=["kuresel"], anahtar_kelimeler=[], min_kaynak=2, buyume_esigi=0)
    assert tur({"bbc": FEEDS["bbc"], "aj": FEEDS["aj"]}, db_yolu, SahteBot(hata=True), bolge_kurali) == 0
    tekrar = SahteBot()
    n = tur({"bbc": FEEDS["bbc"], "aj": FEEDS["aj"]}, db_yolu, tekrar, bolge_kurali)
    assert n >= 1 and all("El Fasher" in m or "Sudan" in m or "RSF" in m or "Japan" in m or "sanctions" in m
                          for m, _ in tekrar.mesajlar), tekrar.mesajlar
    print(bot.mesajlar[1][0])
    print(f"TAMAM · {len(bot.mesajlar) + len(tekrar.mesajlar)} sahte Telegram mesajı")


if __name__ == "__main__":
    calistir()
