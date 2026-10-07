"""Olayları 3. adımdaki site için JSON'a ve okunabilir bir Markdown özetine yazar."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

COGRAFI_DEGIL = {"turkce", "analiz_ve_resmi", "kuresel"}


def _bolge_tahmini(haberler):
    c = Counter(h["bolge"] for h in haberler if h["bolge"] not in COGRAFI_DEGIL)
    return c.most_common(1)[0][0] if c else "kuresel"


def olaylari_getir(con, saat: int):
    sinir = (datetime.now(timezone.utc) - timedelta(hours=saat)).isoformat()
    sonuc = []
    for o in con.execute(
            """SELECT * FROM olay WHERE birlesti IS NULL AND haber_sayisi > 0 AND guncelleme >= ?
               ORDER BY COALESCE(onem, 0) DESC, kaynak_sayisi DESC, guncelleme DESC""", (sinir,)):
        haberler = [dict(r) for r in con.execute(
            "SELECT kaynak, bolge, dil, baslik, link, yayin FROM haber WHERE olay_id=? ORDER BY yayin",
            (o["id"],))]
        sonuc.append({
            "id": o["id"],
            "baslik": o["tr_baslik"] or haberler[0]["baslik"],
            "ozet": o["tr_ozet"],
            "turkce_ozet_var": bool(o["tr_ozet"]),
            "bolge": o["bolge"] or _bolge_tahmini(haberler),
            "ulkeler": json.loads(o["ulkeler"]) if o["ulkeler"] else [],
            "etiketler": json.loads(o["etiketler"]) if o["etiketler"] else [],
            "onem": o["onem"],
            "ilk_haber": o["olusma"], "son_haber": o["guncelleme"],
            "kaynak_sayisi": o["kaynak_sayisi"],
            "kaynaklar": [{"kaynak": h["kaynak"], "baslik": h["baslik"], "link": h["link"],
                           "dil": h["dil"], "yayin": h["yayin"]} for h in haberler],
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
