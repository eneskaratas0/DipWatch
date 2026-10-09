"""Olayları 3. adımdaki site için JSON'a ve okunabilir bir Markdown özetine yazar."""
import json
import re
from datetime import datetime, timedelta, timezone

from . import bolge

try:
    import numpy as np
except ImportError:
    np = None

# Başlık olarak seçilmesin: bunlar olaya bağlı kalır (ve tür etiketi taşır) ama kalıp/özet niteliğinde,
# gerçek gelişmeyi anlatmaz (bkz. fetch.icerik_turu).
_TUR_CANLI = re.compile(r"-\s*live\b|^live[\s:]", re.IGNORECASE)
_TUR_ANALIZ = re.compile(r"^(explainer|analysis|opinion|editorial)\b[\s:-]", re.IGNORECASE)


def _duz_haber(h) -> bool:
    b = h["baslik"].strip()
    return not (_TUR_CANLI.search(b) or _TUR_ANALIZ.match(b))


def _baslik_sec(haberler):
    """Claude özeti yoksa: kümenin merkez (gömme) vektörüne en yakın başlık seçilir -- "Explainer",
    "... - live", "analysis" gibi kalıp başlıklar elenerek. Vektör yoksa (fastembed hiç çalışmadıysa)
    en son Türkçe başlığa, o da yoksa ilk haberin başlığına düşülür. Eşitlikte/yakınlıkta Türkçe tercih edilir."""
    adaylar = [h for h in haberler if _duz_haber(h)] or list(haberler)
    vektorlu = [h for h in adaylar if h.get("vektor")] if np is not None else []
    if len(vektorlu) >= 2:
        vs = np.stack([np.frombuffer(h["vektor"], dtype=np.float32) for h in vektorlu])
        merkez = vs.mean(axis=0)
        benzerlik = vs @ merkez
        en_yuksek = benzerlik.max()
        en_yakinlar = [h for h, b in zip(vektorlu, benzerlik) if b >= en_yuksek - 1e-4]
        turkce = [h for h in en_yakinlar if h["dil"] == "tr"]
        return (turkce or en_yakinlar)[0]["baslik"]
    turkce = [h for h in adaylar if h["dil"] == "tr"]
    return turkce[-1]["baslik"] if turkce else adaylar[0]["baslik"]


def olaylari_getir(con, saat: int):
    sinir = (datetime.now(timezone.utc) - timedelta(hours=saat)).isoformat()
    sonuc = []
    for o in con.execute(
            """SELECT * FROM olay WHERE birlesti IS NULL AND haber_sayisi > 0 AND guncelleme >= ?
               ORDER BY COALESCE(onem, 0) DESC, kaynak_sayisi DESC, guncelleme DESC""", (sinir,)):
        haberler = [dict(r) for r in con.execute(
            """SELECT kaynak, bolge, dil, baslik, ozet, link, yayin, icerik_turu, vektor
               FROM haber WHERE olay_id=? ORDER BY yayin""", (o["id"],))]
        sonuc.append({
            "id": o["id"],
            "baslik": o["tr_baslik"] or _baslik_sec(haberler),
            "ozet": o["tr_ozet"],
            "turkce_ozet_var": bool(o["tr_ozet"]),
            "bolge": o["bolge"] or bolge.tahmin_et(haberler),
            "ulkeler": json.loads(o["ulkeler"]) if o["ulkeler"] else [],
            "etiketler": json.loads(o["etiketler"]) if o["etiketler"] else [],
            "onem": o["onem"],
            "ilk_haber": o["olusma"], "son_haber": o["guncelleme"],
            "kaynak_sayisi": o["kaynak_sayisi"],
            "kaynaklar": [{"kaynak": h["kaynak"], "baslik": h["baslik"], "link": h["link"],
                           "dil": h["dil"], "yayin": h["yayin"], "tur": h["icerik_turu"]} for h in haberler],
        })
    return sonuc


def yaz(con, ayar):
    olaylar = olaylari_getir(con, ayar.export_saat)
    ayar.cikti_klasoru.mkdir(parents=True, exist_ok=True)
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (ayar.cikti_klasoru / "events.json").write_text(
        json.dumps({"olusturulma": simdi, "olaylar": olaylar}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    md = [f"# DipWatch: son {ayar.export_saat} saat", f"_Güncelleme: {simdi} UTC_", ""]
    for o in olaylar:
        if o["kaynak_sayisi"] < 2 and not o["ozet"]:
            continue  # tek kaynaklı, özetsiz olaylar yalnızca JSON'da
        yildiz = "★" * (o["onem"] or 0)
        md.append(f"## {o['baslik']} {yildiz}".rstrip())
        md.append(f"*{o['bolge']} · {o['kaynak_sayisi']} kaynak · son: {o['son_haber'][:16].replace('T', ' ')}*")
        if o["ozet"]:
            md += ["", o["ozet"]]
        md.append("")
        for k in o["kaynaklar"]:
            md.append(f"- [{k['kaynak']}: {k['baslik']}]({k['link']})")
        md.append("")
    (ayar.cikti_klasoru / "son_olaylar.md").write_text("\n".join(md), encoding="utf-8")
    return len(olaylar)
