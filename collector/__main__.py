"""DipWatch toplayıcı.

Kullanım:
  python -m collector tur                 # bir kez çek, grupla, özetle, dışa aktar
  python -m collector dongu --aralik 300  # her 5 dakikada bir tur
  python -m collector feed-durum          # hangi beslemeler çalışıyor / bozuk
"""
import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import cluster, db, export, fetch, summarize
from .config import Ayarlar, kaynaklari_yukle

log = logging.getLogger("dipwatch")
_GOMUCU = []  # dongu modunda model her turda yeniden yüklenmesin


def _gomucu(ayar):
    if not _GOMUCU:
        try:
            from . import embed
            _GOMUCU.append(embed.gomucu(ayar))
        except ImportError:  # numpy yok
            log.info("numpy/fastembed kurulu değil: gömme ile birleştirme atlandı")
            _GOMUCU.append(None)
    return _GOMUCU[0]


def feed_durumu_yaz(con, k, n, hata):
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if hata:
        con.execute("""INSERT INTO feed_durum (ad, url, son_deneme, ardisik_hata, hata) VALUES (?,?,?,1,?)
                       ON CONFLICT(ad) DO UPDATE SET url=excluded.url, son_deneme=excluded.son_deneme,
                       ardisik_hata=ardisik_hata+1, hata=excluded.hata""", (k.ad, k.url, simdi, hata))
    else:
        con.execute("""INSERT INTO feed_durum (ad, url, son_deneme, son_basari, son_oge) VALUES (?,?,?,?,?)
                       ON CONFLICT(ad) DO UPDATE SET url=excluded.url, son_deneme=excluded.son_deneme,
                       son_basari=excluded.son_basari, son_oge=excluded.son_oge, ardisik_hata=0, hata=NULL""",
                    (k.ad, k.url, simdi, simdi, n))


def gomme_ile_birlestir(con, ayar, gom, acilan) -> int:
    from . import embed
    embed.eksikleri_vektorle(con, gom)
    birlesen = 0
    for yeni_id, mevcut_id in embed.birlestirme_onerileri(con, ayar, acilan):
        hedef = cluster.kok_olay(con, mevcut_id)
        if hedef != cluster.kok_olay(con, yeni_id):
            cluster.birlestir(con, hedef, yeni_id)
            birlesen += 1
    con.commit()
    return birlesen


def tur(ayar: Ayarlar, client=None, gom=None):
    """client / gom: None ise ayarlardan oluşturulur, False ise ilgili adım atlanır."""
    con = db.baglan(ayar.veritabani)
    kaynaklar = kaynaklari_yukle(ayar.kaynak_dosyasi)
    sonuclar = fetch.hepsini_cek(kaynaklar, ayar.paralel, ayar.zaman_asimi)

    # 1) Yeni haberleri ayıkla
    yeni = []
    gorulen = set()
    for k, haberler, hata in sonuclar:
        feed_durumu_yaz(con, k, len(haberler), hata)
        for h in haberler:
            if h["link"] in gorulen:
                continue
            gorulen.add(h["link"])
            if con.execute("SELECT 1 FROM haber WHERE link=?", (h["link"],)).fetchone():
                continue
            yeni.append(h)
    yeni.sort(key=lambda h: h["yayin"])

    # 2) Olaylara grupla
    g = cluster.Gruplayici(con, ayar)
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    degisen, acilan = set(), []
    for h in yeni:
        oid, yeni_mi = g.ata(h)
        con.execute("""INSERT INTO haber (link, kaynak, bolge, dil, tur, baslik, ozet, yayin, eklenme, olay_id)
                       VALUES (:link,:kaynak,:bolge,:dil,:tur,:baslik,:ozet,:yayin,:eklenme,:olay_id)""",
                    {**h, "eklenme": simdi, "olay_id": oid})
        degisen.add(oid)
        if yeni_mi:
            acilan.append(oid)
    cluster.olay_sayaclarini_guncelle(con, degisen)
    con.commit()

    # 3) Gömme modeli: diller arası birleştirme (anahtarsız)
    if gom is None:
        gom = _gomucu(ayar)
    gomme_birlesen = gomme_ile_birlestir(con, ayar, gom, acilan) if gom else 0

    # 4) Claude: kalan diller arası birleştirme + Türkçe özet
    if client is None:
        client = summarize.istemci()
    birlesen = ozetlenen = 0
    if client:
        if ayar.llm_birlestirme:
            for yeni_id, mevcut_id in summarize.birlestirme_onerileri(con, ayar, client, acilan):
                hedef = cluster.kok_olay(con, mevcut_id)
                if hedef != cluster.kok_olay(con, yeni_id):
                    cluster.birlestir(con, hedef, yeni_id)
                    birlesen += 1
            con.commit()
        ozetlenen = summarize.ozetle(con, ayar, client)
    else:
        log.info("Claude kimlik bilgisi yok: Türkçe özet ve diller arası birleştirme atlandı")

    n_olay = export.yaz(con, ayar)
    hatali = sum(1 for _, _, h in sonuclar if h)
    log.info("feed: %d/%d çalıştı · yeni haber: %d · yeni olay: %d · gömme ile birleşen: %d · Claude ile birleşen: %d"
             " · özetlenen: %d · dışa aktarılan olay: %d",
             len(sonuclar) - hatali, len(sonuclar), len(yeni), len(acilan), gomme_birlesen, birlesen, ozetlenen, n_olay)
    con.close()


def feed_durum(ayar: Ayarlar):
    con = db.baglan(ayar.veritabani)
    satirlar = con.execute("SELECT * FROM feed_durum ORDER BY ardisik_hata DESC, ad").fetchall()
    for r in satirlar:
        durum = "OK " if r["ardisik_hata"] == 0 else f"HATA x{r['ardisik_hata']}"
        print(f"{durum:9} {r['ad']:32} öğe={r['son_oge']:<4} {r['hata'] or ''}")


def main():
    p = argparse.ArgumentParser(prog="collector")
    p.add_argument("komut", choices=["tur", "dongu", "feed-durum"])
    p.add_argument("--aralik", type=int, default=300, help="dongu: turlar arası saniye")
    p.add_argument("--kaynaklar", type=Path, help="sources.yaml yerine başka bir dosya")
    p.add_argument("--db", type=Path)
    p.add_argument("--cikti", type=Path)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ayar = Ayarlar()
    if a.kaynaklar:
        ayar.kaynak_dosyasi = a.kaynaklar
    if a.db:
        ayar.veritabani = a.db
    if a.cikti:
        ayar.cikti_klasoru = a.cikti

    if a.komut == "feed-durum":
        return feed_durum(ayar)
    if a.komut == "tur":
        return tur(ayar)
    while True:
        try:
            tur(ayar)
        except Exception:
            log.exception("tur başarısız; bir sonrakinde yeniden denenecek")
        time.sleep(a.aralik)


if __name__ == "__main__":
    main()
