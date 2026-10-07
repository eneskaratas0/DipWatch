"""Haberleri olaylara gruplar.

Yöntem: başlık (x2) + açıklama üzerinden TF-IDF vektörü; her yeni haber, son
`olay_penceresi_saat` içinde güncellenmiş olayların merkez vektörüyle karşılaştırılır.
Benzerlik eşiği aşılırsa o olaya katılır, aşılmazsa yeni olay açılır.
Kelimeler ilk 6 harfe kırpılır: Türkçe ekleri ve İngilizce çoğulları kabaca toparlar.
Farklı dillerdeki aynı olay burada birleşmez; bunu summarize.birlestir() yapar.
"""
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

DURAK = set("""
a an and are as at be been but by for from has have he her his in into is it its
not of on or over says said say that the their they this to up was were what when
which who will with after amid new more than about against also could would how
us u.s why after before back first last week year years day news live latest update
ve ile bir bu da de için olarak olan gibi daha çok ama en ise ki mi mı ne şu o
sonra önce kadar yeni dedi açıkladı göre karşı üzerine son dakika haber haberi
""".split())
_KELIME = re.compile(r"[a-zçğıöşüâîû0-9]+")


def kelimeler(metin: str) -> list[str]:
    # İ/I/ı hepsi "i"ye: Türkçe ve İngilizce büyük-küçük harf farkını eşitler
    metin = metin.replace("İ", "i").lower().replace("ı", "i")
    return [w[:6] for w in _KELIME.findall(metin) if len(w) >= 3 and w not in DURAK]


def belge(h) -> list[str]:
    return kelimeler(h["baslik"]) * 2 + kelimeler(h["ozet"] or "")


class Gruplayici:
    def __init__(self, con, ayar):
        self.con, self.ayar = con, ayar
        simdi = datetime.now(timezone.utc)
        idf_sinir = (simdi - timedelta(hours=ayar.idf_penceresi_saat)).isoformat()
        olay_sinir = (simdi - timedelta(hours=ayar.olay_penceresi_saat)).isoformat()
        satirlar = con.execute("SELECT baslik, ozet FROM haber WHERE yayin >= ?", (idf_sinir,)).fetchall()
        self.df, self.n = Counter(), 0
        for s in satirlar:
            self._df_ekle(belge(s))
        # Aktif olayların ham terim toplamları
        self.olaylar: dict[int, Counter] = {}
        for s in con.execute(
            """SELECT h.olay_id, h.baslik, h.ozet FROM haber h JOIN olay o ON o.id = h.olay_id
               WHERE o.guncelleme >= ? AND o.birlesti IS NULL""", (olay_sinir,)):
            self.olaylar.setdefault(s["olay_id"], Counter()).update(belge(s))

    def _df_ekle(self, terimler):
        self.n += 1
        self.df.update(set(terimler))

    def _vektor(self, sayac: Counter) -> dict:
        v = {t: (1 + math.log(c)) * math.log((1 + self.n) / (1 + self.df[t])) for t, c in sayac.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def _kos(a: dict, b: dict) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())

    def ata(self, h) -> tuple[int, bool]:
        """Haberi bir olaya atar; (olay_id, yeni_mi) döndürür."""
        terimler = belge(h)
        self._df_ekle(terimler)
        hv = self._vektor(Counter(terimler))
        en_iyi, skor = None, 0.0
        for oid, sayac in self.olaylar.items():
            s = self._kos(hv, self._vektor(sayac))
            if s > skor:
                en_iyi, skor = oid, s
        if en_iyi is not None and skor >= self.ayar.benzerlik_esigi:
            self.olaylar[en_iyi].update(terimler)
            return en_iyi, False
        oid = self.con.execute("INSERT INTO olay (olusma, guncelleme) VALUES (?, ?)",
                               (h["yayin"], h["yayin"])).lastrowid
        self.olaylar[oid] = Counter(terimler)
        return oid, True


def olay_sayaclarini_guncelle(con, olay_idler):
    for oid in olay_idler:
        con.execute(
            """UPDATE olay SET
                 haber_sayisi = (SELECT COUNT(*) FROM haber WHERE olay_id = :o),
                 kaynak_sayisi = (SELECT COUNT(DISTINCT kaynak) FROM haber WHERE olay_id = :o),
                 olusma = (SELECT MIN(yayin) FROM haber WHERE olay_id = :o),
                 guncelleme = (SELECT MAX(yayin) FROM haber WHERE olay_id = :o)
               WHERE id = :o""", {"o": oid})


def kok_olay(con, oid: int) -> int:
    """Birleştirilmiş olay zincirini izleyip asıl olayı döndürür."""
    while True:
        r = con.execute("SELECT birlesti FROM olay WHERE id=?", (oid,)).fetchone()
        if not r or r["birlesti"] is None:
            return oid
        oid = r["birlesti"]


def birlestir(con, hedef: int, kaynak: int):
    """`kaynak` olayının haberlerini `hedef` olaya taşır."""
    con.execute("UPDATE haber SET olay_id = ? WHERE olay_id = ?", (hedef, kaynak))
    con.execute("UPDATE olay SET birlesti = ?, haber_sayisi = 0 WHERE id = ?", (hedef, kaynak))
    olay_sayaclarini_guncelle(con, [hedef])
