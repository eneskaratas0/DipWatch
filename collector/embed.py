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


def birlestirme_onerileri(con, ayar, acilan: list[int]) -> list[tuple[int, int]]:
    """(yeni_olay, mevcut_olay) çiftleri: yeni olay, benzerliği eşiği geçen en yakın aktif olaya."""
    if not acilan:
        return []
    sinir = (datetime.now(timezone.utc) - timedelta(hours=ayar.olay_penceresi_saat)).isoformat()
    toplam: dict[int, np.ndarray] = {}
    for s in con.execute(
            """SELECT h.olay_id, h.vektor FROM haber h JOIN olay o ON o.id = h.olay_id
               WHERE o.birlesti IS NULL AND o.guncelleme >= ? AND h.vektor IS NOT NULL""", (sinir,)):
        v = np.frombuffer(s["vektor"], dtype=np.float32)
        toplam[s["olay_id"]] = toplam.get(s["olay_id"], 0) + v
    if len(toplam) < 2:
        return []
    idler = list(toplam)
    merkez = np.stack([toplam[i] for i in idler])
    merkez /= np.maximum(np.linalg.norm(merkez, axis=1, keepdims=True), 1e-9)
    sira = {oid: n for n, oid in enumerate(idler)}

    oneriler = []
    for yeni in acilan:
        if yeni not in sira:
            continue
        benz = merkez @ merkez[sira[yeni]]
        benz[sira[yeni]] = -1
        en_iyi = int(np.argmax(benz))
        if benz[en_iyi] >= ayar.gomme_esigi:
            oneriler.append((yeni, idler[en_iyi]))
            if log.isEnabledFor(logging.DEBUG):
                b = [con.execute("SELECT baslik FROM haber WHERE olay_id=? LIMIT 1", (o,)).fetchone()[0]
                     for o in (yeni, idler[en_iyi])]
                log.debug("%.2f  %s  <->  %s", benz[en_iyi], b[0][:70], b[1][:70])
    return oneriler
