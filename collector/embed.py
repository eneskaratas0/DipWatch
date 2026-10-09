"""Çok dilli gömme modeliyle olay birleştirme (API anahtarı gerekmez).

TF-IDF aynı dildeki ve benzer kelimeli haberleri gruplar; "Vance: İran zenginleştirmeyi azaltmalı" ile
"Vance says Iran must cut enrichment" gibi farklı dillerdeki ya da farklı kelimelerle yazılmış aynı
haberi kaçırır. Burada her başlık çok dilli bir modelle anlam vektörüne çevrilir ve yeni açılan her olay,
aktif olayların ortalama vektörüyle karşılaştırılır. Benzerlik eşiği geçerse olaylar birleştirilir.

Model ilk kullanımda indirilir (~220 MB) ve bilgisayarda çalışır; fastembed kurulu değilse adım atlanır.
"""
import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from .cluster import PENCERE_N

log = logging.getLogger("dipwatch.gomme")


class Gomucu:
    """Metin listesini birim uzunlukta vektörlere çevirir."""

    def __init__(self, model_adi: str):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_adi)

    def __call__(self, metinler: list[str]) -> np.ndarray:
        v = np.array(list(self.model.embed(metinler)), dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def gomucu(ayar):
    """Ayarlarda açıksa ve fastembed kuruluysa Gomucu, yoksa None."""
    if not ayar.gomme_birlestirme:
        return None
    try:
        return Gomucu(ayar.gomme_modeli)
    except ImportError:
        log.info("fastembed kurulu değil: gömme ile birleştirme atlandı (pip install fastembed)")
    except Exception as ex:  # model indirilemedi vb.
        log.warning("gömme modeli yüklenemedi, adım atlandı: %s", ex)
    return None


def eksikleri_vektorle(con, gom) -> int:
    """Vektörü olmayan haberlerin başlıklarını vektöre çevirip saklar."""
    satirlar = con.execute("SELECT id, baslik FROM haber WHERE vektor IS NULL").fetchall()
    for i in range(0, len(satirlar), 256):
        parca = satirlar[i:i + 256]
        vektorler = gom([s["baslik"] for s in parca])
        con.executemany("UPDATE haber SET vektor=? WHERE id=?",
                        [(v.tobytes(), s["id"]) for v, s in zip(vektorler, parca)])
    return len(satirlar)


def birlestirme_onerileri(con, ayar, adaylar: list[int] | None = None) -> list[tuple[int, int]]:
    """(zayıf_olay, güçlü_olay) çiftleri: benzerliği eşiği geçen en yakın aktif olay eşleri.
    `adaylar` verilirse yalnızca onlar için en iyi eşleşme aranır (örn. bu turda yeni açılanlar);
    None ise TÜM aktif olaylar yeniden değerlendirilir ("periyodik birleştirme" - yalnızca yeni açılan
    olaylara bakmak, zamanla birbirinden ayrı açılmış aynı olayı bir daha asla karşılaştırmaz).
    Eşiği geçen çiftte "zayıf" olan (daha az kaynaklı, eşitlikte daha yeni) ilk elemanda döner; böylece
    çağıran taraf küçük olayı köklü olana katar, tersini değil."""
    sinir = (datetime.now(timezone.utc)
             - timedelta(hours=ayar.gomme_birlestirme_penceresi_saat)).isoformat()
    # Merkez, olaya katılan SON PENCERE_N haberle sınırlıdır (h.id DESC): aksi halde çok habere ulaşan
    # bir olayın merkezi gittikçe genelleşip ("Houthi/Yemen" gibi ortak bir temaya) ilgisiz haberleri de
    # kendine çekerek mega-olaylar oluşturabilir (bkz. cluster.py'deki aynı mantık, PENCERE_N).
    toplam: dict[int, np.ndarray] = {}
    kaynaklar: dict[int, int] = {}
    sayim: dict[int, int] = {}
    for s in con.execute(
            """SELECT h.olay_id, h.vektor, o.kaynak_sayisi FROM haber h JOIN olay o ON o.id = h.olay_id
               WHERE o.birlesti IS NULL AND o.guncelleme >= ? AND h.vektor IS NOT NULL
               ORDER BY h.id DESC""", (sinir,)):
        oid = s["olay_id"]
        if sayim.get(oid, 0) >= PENCERE_N:
            continue
        v = np.frombuffer(s["vektor"], dtype=np.float32)
        toplam[oid] = toplam.get(oid, 0) + v
        kaynaklar[oid] = s["kaynak_sayisi"]
        sayim[oid] = sayim.get(oid, 0) + 1
    if len(toplam) < 2:
        return []
    idler = list(toplam)
    merkez = np.stack([toplam[i] for i in idler])
    merkez /= np.maximum(np.linalg.norm(merkez, axis=1, keepdims=True), 1e-9)
    sira = {oid: n for n, oid in enumerate(idler)}
    sorgu = [oid for oid in (adaylar if adaylar is not None else idler) if oid in sira]

    oneriler = []
    for olay in sorgu:
        benz = merkez @ merkez[sira[olay]]
        benz[sira[olay]] = -1
        en_iyi = int(np.argmax(benz))
        if benz[en_iyi] < ayar.gomme_esigi:
            continue
        hedef = idler[en_iyi]
        zayif, guclu = olay, hedef
        if (kaynaklar[zayif], -zayif) > (kaynaklar[guclu], -guclu):
            zayif, guclu = guclu, zayif
        oneriler.append((zayif, guclu))
        if log.isEnabledFor(logging.DEBUG):
            b = [con.execute("SELECT baslik FROM haber WHERE olay_id=? LIMIT 1", (o,)).fetchone()[0]
                 for o in (zayif, guclu)]
            log.debug("%.2f  %s  <->  %s", benz[en_iyi], b[0][:70], b[1][:70])
    return list(dict.fromkeys(oneriler))  # A ve B birbirini önerdiyse tekrarı at
