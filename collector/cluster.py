"""Haberleri olaylara gruplar.

Yöntem: başlık (x2) + açıklama üzerinden TF-IDF vektörü; her yeni haber, son
`olay_penceresi_saat` içinde güncellenmiş olayların merkez vektörüyle karşılaştırılır.
Benzerlik eşiği aşılırsa o olaya katılır, aşılmazsa yeni olay açılır.
Kelimeler ilk 6 harfe kırpılır: Türkçe ekleri ve İngilizce çoğulları kabaca toparlar.

Bir olayın vektörü, kümeye katılan SON `PENCERE_N` haberin terimleriyle sınırlıdır (ilk haberin
etkisi sabit kalıp olayı sonsuza kadar çekmesin; konu zamanla kayarsa eski terimler düşsün).
Rakam ve büyük harfle başlayan (özel isim olması muhtemel) terimlere ekstra ağırlık verilir: kalıp
başlıklar ("... Ödülü sahibini buldu") genelde yalnızca bu terimlerle (laureat adı, yıl, kategori)
birbirinden ayrılır, aksi halde IDF'nin düşürdüğü ortak kelimeler üzerinden yanlışlıkla eşleşebilir.

Farklı dillerdeki aynı olay burada birleşmez; bunu embed.py / summarize.birlestir() yapar.
"""
import math
import re
from collections import Counter, deque
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
_KELIME_HAM = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+")

PENCERE_N = 15       # bir olayın vektörü en fazla bu kadar haberin terimlerinden oluşur
AYIRT_CARPAN = 1.8   # rakam / özel isim olması muhtemel terimlere ekstra ağırlık


def kelimeler(metin: str) -> list[str]:
    # İ/I/ı hepsi "i"ye: Türkçe ve İngilizce büyük-küçük harf farkını eşitler
    metin = metin.replace("İ", "i").lower().replace("ı", "i")
    return [w[:6] for w in _KELIME.findall(metin) if len(w) >= 3 and w not in DURAK]


def _normalle(w: str) -> str:
    return w.replace("İ", "i").lower().replace("ı", "i")[:6]


def ayirt_edici(metin: str) -> set[str]:
    """Rakam içeren ya da cümle içinde büyük harfle başlayan (özel isim olması muhtemel) terimler;
    kelimeler() ile aynı normalizasyonla. _vektor()'da bunlara ekstra ağırlık verilir."""
    sonuc = set()
    for w in _KELIME_HAM.findall(metin):
        if not (any(c.isdigit() for c in w) or w[0].isupper()):
            continue
        n = _normalle(w)
        if len(n) >= 3 and n not in DURAK:
            sonuc.add(n)
    return sonuc


def _al(h, anahtar, varsayilan=None):
    """h bir dict ya da sqlite3.Row olabilir; ikisi de [] ile erişilir ama eksik anahtarda biri
    KeyError biri IndexError fırlatır, .get() ise yalnızca dict'te var."""
    try:
        v = h[anahtar]
    except (KeyError, IndexError):
        return varsayilan
    return varsayilan if v is None else v


def belge(h) -> list[str]:
    return kelimeler(h["baslik"]) * 2 + kelimeler(h["ozet"] or "")


def belge_ayirt_edici(h) -> set[str]:
    return ayirt_edici(h["baslik"]) | ayirt_edici(h["ozet"] or "")


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
        # Aktif olayların terim kayıtları: her olay için en fazla son PENCERE_N haberin
        # (terimler, ayırt_edici_terimler) çifti; en yeni haberler id DESC ile seçilir.
        gecici: dict[int, list] = {}
        for s in con.execute(
            """SELECT h.olay_id, h.baslik, h.ozet FROM haber h JOIN olay o ON o.id = h.olay_id
               WHERE o.guncelleme >= ? AND o.birlesti IS NULL ORDER BY h.id DESC""", (olay_sinir,)):
            liste = gecici.setdefault(s["olay_id"], [])
            if len(liste) < PENCERE_N:
                liste.append((belge(s), belge_ayirt_edici(s)))
        self.olaylar: dict[int, deque] = {oid: deque(kayit, maxlen=PENCERE_N) for oid, kayit in gecici.items()}

    def _df_ekle(self, terimler):
        self.n += 1
        self.df.update(set(terimler))

    def _vektor(self, kayitlar) -> dict:
        """kayitlar: (terimler, ayırt_edici_terimler) çiftlerinin listesi/deque'si."""
        sayac = Counter()
        ayirt = set()
        for terimler, ayirt_terimler in kayitlar:
            sayac.update(terimler)
            ayirt |= ayirt_terimler
        v = {}
        for t, c in sayac.items():
            agirlik = AYIRT_CARPAN if t in ayirt else 1.0
            v[t] = agirlik * (1 + math.log(c)) * math.log((1 + self.n) / (1 + self.df[t]))
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
        ayirt = belge_ayirt_edici(h)
        hv = self._vektor([(terimler, ayirt)])
        en_iyi, skor = None, 0.0
        for oid, kayit in self.olaylar.items():
            s = self._kos(hv, self._vektor(kayit))
            if s > skor:
                en_iyi, skor = oid, s
        esik = self.ayar.benzerlik_esigi
        if _al(h, "icerik_turu", "haber") != "haber":
            # Explainer/analiz/canlı başlıklar genelde şablon ağırlıklı ve zaten var olan bir olayı
            # konu alır; tek başına yeni bir olay açmasın diye daha gevşek bir eşikle bağlanmaya çalışılır.
            esik *= 0.5
        if en_iyi is not None and skor >= esik:
            self.olaylar[en_iyi].append((terimler, ayirt))
            return en_iyi, False
        oid = self.con.execute("INSERT INTO olay (olusma, guncelleme) VALUES (?, ?)",
                               (h["yayin"], h["yayin"])).lastrowid
        self.olaylar[oid] = deque([(terimler, ayirt)], maxlen=PENCERE_N)
        return oid, True

    def birlestir_ici(self, hedef: int, kaynak: int):
        """DB'de kaynak->hedef birleştirildiğinde (bkz. birlestir()) bellekteki durumu da
        senkronlar: idf istatistiklerini (self.df/self.n) yeniden taramaya gerek kalmadan, yalnızca
        kaynak'ın terim kayıtlarını hedefe taşır. Çağrılmazsa kaynak'ın bellekteki eski vektörü
        yanlışlıkla eşleşmeye devam edebilir ya da haber birleşmiş bir olaya (`birlesti` dolu)
        atanabilir."""
        kayit = self.olaylar.pop(kaynak, None)
        if kayit is None:
            return
        hedef_kayit = self.olaylar.setdefault(hedef, deque(maxlen=PENCERE_N))
        for terimler, ayirt in kayit:
            hedef_kayit.append((terimler, ayirt))


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
