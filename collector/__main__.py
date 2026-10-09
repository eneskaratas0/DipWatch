"""DipWatch toplayıcı.

Kullanım:
  python -m collector tur                 # bir kez çek, grupla, özetle, dışa aktar
  python -m collector dongu --aralik 300  # her 5 dakikada bir tur
  python -m collector feed-durum          # hangi beslemeler çalışıyor / bozuk
  python -m collector yeniden-grupla       # son 72 saatin haberlerini sıfırdan gruplar (önce yedek alır)
  python -m collector telegram-chat-id    # bota yazan sohbetlerin kimliğini göster (.env için)
  python -m collector telegram-test       # Telegram'a deneme mesajı gönder
  --site eklenirse her turdan sonra public/ klasöründeki site de yeniden oluşturulur.
"""
import argparse
import contextlib
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cluster, db, export, fetch, summarize, telegram
from .config import KOK, Ayarlar, kaynaklari_yukle

log = logging.getLogger("dipwatch")
_GOMUCU = []  # dongu modunda model her turda yeniden yüklenmesin
_KILIT_ESKI_SANIYE = 1800  # 30 dk: bu süreden eski bir kilit, çökmüş bir süreçten kalmış sayılır


@contextlib.contextmanager
def _db_kilidi(ayar: Ayarlar):
    """`tur()`/`dongu` ile `yeniden-grupla` aynı veritabanında eşzamanlı çalışırsa birbirinin
    olay_id atamalarının üzerine yazabilir (ikisi de aynı pencerede haber taşır/yeniden gruplar).
    Bu basit dosya kilidi ikisinin aynı anda çalışmasını önler. Kilit tutuluyorsa RuntimeError
    fırlatır -- `dongu` zaten bunu yakalayıp bir sonraki turda yeniden dener (bkz. main()); tek
    seferlik `tur`/`yeniden-grupla` çalıştırmalarında hata açıkça görünür. 30 dakikadan eski bir
    kilit, çökmüş bir süreçten kalmış sayılıp kendiliğinden temizlenir."""
    kilit_yolu = ayar.veritabani.with_name(ayar.veritabani.name + ".lock")
    try:
        if kilit_yolu.exists() and time.time() - kilit_yolu.stat().st_mtime > _KILIT_ESKI_SANIYE:
            log.warning("eski kilit dosyası (%s) temizlendi: önceki çalışma çökmüş olabilir", kilit_yolu)
            kilit_yolu.unlink()
        fd = os.open(kilit_yolu, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"{kilit_yolu} kilit dosyası var: başka bir 'tur'/'dongu'/'yeniden-grupla' aynı "
            "veritabanında çalışıyor olabilir. Eminsen elle sil ve tekrar dene.")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        kilit_yolu.unlink(missing_ok=True)


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


def gomme_ile_birlestir(con, ayar, gom, adaylar, g=None) -> list[tuple[int, int]]:
    """adaylar: yalnızca bu olaylar için en iyi eşleşme aranır; None ise tüm aktif olaylar
    (periyodik birleştirme). g verilirse (bkz. yeniden_grupla) uygulanan her birleşme Gruplayici'nin
    bellekteki durumuna da (idf'i yeniden taramadan) yansıtılır. (hedef, kaynak) çiftlerini döndürür."""
    from . import embed
    embed.eksikleri_vektorle(con, gom)
    uygulanan = []
    for zayif_id, guclu_id in embed.birlestirme_onerileri(con, ayar, adaylar):
        hedef = cluster.kok_olay(con, guclu_id)
        if hedef != cluster.kok_olay(con, zayif_id):
            cluster.birlestir(con, hedef, zayif_id)
            if g is not None:
                g.birlestir_ici(hedef, zayif_id)
            uygulanan.append((hedef, zayif_id))
    con.commit()
    return uygulanan


def tur(ayar: Ayarlar, client=None, gom=None, bot=None):
    """client / gom / bot: None ise ayarlardan oluşturulur, False ise ilgili adım atlanır."""
    with _db_kilidi(ayar):
        con = db.baglan(ayar.veritabani)
        kaynaklar = kaynaklari_yukle(ayar.kaynak_dosyasi)
        sonuclar = fetch.hepsini_cek(kaynaklar, ayar.paralel, ayar.zaman_asimi)

        # 1) Yeni haberleri ayıkla: aynı link'i (linkten) ya da aynı kaynaktan normalize edilmiş aynı
        # başlığı (ör. Google News'in aynı haberi farklı yönlendirme kimlikleriyle iki kez döndürmesi)
        # ikinci kez eklemez. Başlık tekrarı denetimi son 14 gündeki haberlerle sınırlı: bir kaynağın aynı
        # başlığı aylar sonra yeniden kullanması (ör. yıl dönümü haberleri) farklı bir haber sayılsın.
        yeni = []
        gorulen_link, gorulen_baslik = set(), set()
        tekrar_sinir = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        for k, haberler, hata in sonuclar:
            feed_durumu_yaz(con, k, len(haberler), hata)
            for h in haberler:
                if h["link"] in gorulen_link:
                    continue
                gorulen_link.add(h["link"])
                if con.execute("SELECT 1 FROM haber WHERE link=?", (h["link"],)).fetchone():
                    continue
                anahtar = (h["kaynak"], h["baslik_norm"])
                if anahtar in gorulen_baslik:
                    continue
                if con.execute("SELECT 1 FROM haber WHERE kaynak=? AND baslik_norm=? AND yayin>=?",
                               (h["kaynak"], h["baslik_norm"], tekrar_sinir)).fetchone():
                    continue
                gorulen_baslik.add(anahtar)
                yeni.append(h)
        yeni.sort(key=lambda h: h["yayin"])

        # 2) Olaylara grupla
        g = cluster.Gruplayici(con, ayar)
        simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
        degisen, acilan = set(), []
        for h in yeni:
            oid, yeni_mi = g.ata(h)
            con.execute("""INSERT INTO haber (link, kaynak, bolge, dil, tur, baslik, ozet, baslik_norm,
                               icerik_turu, yayin, eklenme, olay_id)
                           VALUES (:link,:kaynak,:bolge,:dil,:tur,:baslik,:ozet,:baslik_norm,
                               :icerik_turu,:yayin,:eklenme,:olay_id)""",
                        {**h, "eklenme": simdi, "olay_id": oid})
            degisen.add(oid)
            if yeni_mi:
                acilan.append(oid)
        cluster.olay_sayaclarini_guncelle(con, degisen)
        con.commit()

        # 3) Gömme modeli: diller arası birleştirme (anahtarsız). Yalnızca bu turda açılan olaylara değil,
        # tüm aktif olaylara bakılır ("periyodik birleştirme"): bir olay yalnızca açıldığı anda kontrol
        # edilirse, aynı konunun saatler/günler sonra başka dilde/kaynaktan açılan hali bir daha hiç
        # karşılaştırılmaz (bkz. embed.birlestirme_onerileri docstring'i).
        if gom is None:
            gom = _gomucu(ayar)
        gomme_birlesen = len(gomme_ile_birlestir(con, ayar, gom, None)) if gom else 0

        # 4) Claude: kalan diller arası birleştirme + Türkçe özet
        if client is None:
            client = summarize.istemci()
        birlesen = ozetlenen = 0
        if client:
            if ayar.llm_birlestirme and getattr(client, "birlestirme", True):
                for yeni_id, mevcut_id in summarize.birlestirme_onerileri(con, ayar, client, acilan):
                    hedef = cluster.kok_olay(con, mevcut_id)
                    if hedef != cluster.kok_olay(con, yeni_id):
                        cluster.birlestir(con, hedef, yeni_id)
                        birlesen += 1
                con.commit()
            ozetlenen = summarize.ozetle(con, ayar, client)
        else:
            log.info("LLM anahtarı yok (ANTHROPIC/GEMINI/GROQ): Türkçe özet ve diller arası birleştirme atlandı")

        n_olay = export.yaz(con, ayar)

        # 5) Telegram: seçilen bölge / anahtar kelimelerde yeni veya büyüyen olaylar (.env'de anahtar yoksa atlanır)
        bildirilen = 0
        if bot is not False:
            try:
                bildirilen = telegram.bildir(con, ayar, bot)
            except Exception:
                log.exception("Telegram bildirimi başarısız; bir sonraki turda yeniden denenecek")
        hatali = sum(1 for _, _, h in sonuclar if h)
        log.info("feed: %d/%d çalıştı · yeni haber: %d · yeni olay: %d · gömme ile birleşen: %d · Claude ile birleşen: %d"
                 " · özetlenen: %d · dışa aktarılan olay: %d · Telegram mesajı: %d",
                 len(sonuclar) - hatali, len(sonuclar), len(yeni), len(acilan), gomme_birlesen, birlesen, ozetlenen, n_olay, bildirilen)
        con.close()


def yeniden_grupla(ayar: Ayarlar, saat: int | None = None, client=None, gom=None) -> dict:
    """Son `saat` saatin (varsayılan: ayar.export_saat) haberlerini mevcut olay atamalarından
    bağımsız olarak sıfırdan gruplar: düzeltilmiş kümeleme/bölge/birleştirme mantığını MEVCUT
    veriye uygulamak için kullanılır. Önce veritabanının yedeğini alır."""
    with _db_kilidi(ayar):
        saat = saat or ayar.export_saat
        con0 = db.baglan(ayar.veritabani)  # yoksa oluştur, şema güncellensin
        con0.close()
        yedek = ayar.veritabani.with_name(
            f"{ayar.veritabani.stem}.{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.bak{ayar.veritabani.suffix}")
        shutil.copy(ayar.veritabani, yedek)
        log.info("yedek alındı: %s", yedek)

        con = db.baglan(ayar.veritabani)

        # 0) Bu sütunlar eklenmeden önce yazılmış eski satırları tazele: tekrar denetimi ve içerik türü
        # etiketi tüm veritabanında geçerli olsun, yalnızca yeniden gruplanan pencerede değil.
        eksik = con.execute("SELECT id, baslik FROM haber WHERE baslik_norm IS NULL").fetchall()
        con.executemany("UPDATE haber SET baslik_norm=?, icerik_turu=? WHERE id=?",
                        [(fetch.baslik_normalle(r["baslik"]), fetch.icerik_turu(r["baslik"]), r["id"])
                         for r in eksik])
        con.commit()

        # 0b) "Careers at Arab News" gibi haber olmayan satırları (kariyer/hakkımızda/abonelik/künye
        # sayfaları) pencereden bağımsız olarak sil: fetch.py'deki filtre yalnızca BUNDAN SONRA çekilecek
        # haberleri kapsar, veritabanında zaten duran eski kayıtları temizlemez.
        tum_satirlar = con.execute("SELECT id, kaynak, baslik, olay_id FROM haber").fetchall()
        gecersiz = [r for r in tum_satirlar if fetch.gecersiz_baslik_mi(r["baslik"])]
        if gecersiz:
            con.executemany("DELETE FROM haber WHERE id=?", [(r["id"],) for r in gecersiz])
            con.commit()
            cluster.olay_sayaclarini_guncelle(
                con, {r["olay_id"] for r in gecersiz if r["olay_id"] is not None})
            con.commit()
            log.info("haber olmayan %d satır silindi: %s", len(gecersiz),
                     [f"[{r['kaynak']}] {r['baslik']!r}" for r in gecersiz])

        sinir = (datetime.now(timezone.utc) - timedelta(hours=saat)).isoformat()
        pencere = con.execute(
            """SELECT id, kaynak, baslik, ozet, baslik_norm, icerik_turu, yayin, olay_id
               FROM haber WHERE yayin >= ? ORDER BY yayin, id""", (sinir,)).fetchall()
        eski_olaylar = {r["olay_id"] for r in pencere if r["olay_id"] is not None}

        # 1) Pencere içindeki tam tekrarları (aynı kaynak + normalize başlık) at: en eskisi kalır.
        gorulen, silinecek = set(), []
        for r in pencere:
            anahtar = (r["kaynak"], r["baslik_norm"])
            if anahtar in gorulen:
                silinecek.append(r["id"])
            else:
                gorulen.add(anahtar)
        if silinecek:
            con.executemany("DELETE FROM haber WHERE id=?", [(i,) for i in silinecek])
            con.commit()
        silinecek_s = set(silinecek)
        pencere = [r for r in pencere if r["id"] not in silinecek_s]

        # 2) Pencereyi eski olay atamalarından ayır; eski olayların sayaçları kalan (pencere dışı)
        # haberlerine göre güncellensin (Gruplayici hangi olayların hâlâ "aktif" olduğuna böyle doğru karar verir).
        con.executemany("UPDATE haber SET olay_id=NULL WHERE id=?", [(r["id"],) for r in pencere])
        con.commit()
        cluster.olay_sayaclarini_guncelle(con, eski_olaylar)
        con.commit()

        # 3) Sıfırdan kümele; her yeni olay açıldığında o anki TÜM aktif olaylarla gömme benzerliğine
        # bakılır (bkz. embed.birlestirme_onerileri). Bir birleşme olursa Gruplayici'nin bellekteki
        # durumu idf'i yeniden taramadan senkronlanır (g=g); ~3000 satırlık bir pencerede her birleşmede
        # idf'i baştan taramak dakikalar sürebilir, incremental senkron saniyeler içinde biter.
        # eski_yeni: her haberin ESKİ olay_id'sinden o anda atandığı YENİ olay_id'ye eşleme (son haber
        # kazanır); bildirim takibini (Telegram) bu pencerenin yeniden gruplanmasından önceki duruma göre
        # güncellemek için kullanılır -- bkz. telegram.gecisleri_uygula.
        if gom is None:
            gom = _gomucu(ayar)
        g = cluster.Gruplayici(con, ayar)
        acilan_toplam, gomme_birlesen, eski_yeni = [], 0, {}
        for i, r in enumerate(pencere):
            h = {"baslik": r["baslik"], "ozet": r["ozet"], "icerik_turu": r["icerik_turu"], "yayin": r["yayin"]}
            oid, yeni_mi = g.ata(h)
            con.execute("UPDATE haber SET olay_id=? WHERE id=?", (oid, r["id"]))
            cluster.olay_sayaclarini_guncelle(con, [oid])
            if r["olay_id"] is not None:
                eski_yeni[r["olay_id"]] = oid
            if yeni_mi:
                acilan_toplam.append(oid)
                if gom:
                    gomme_birlesen += len(gomme_ile_birlestir(con, ayar, gom, [oid], g=g))
            if (i + 1) % 200 == 0:
                log.info("yeniden-grupla: %d/%d haber kümelendi (%d yeni olay, %d gömme ile birleşti)",
                         i + 1, len(pencere), len(acilan_toplam), gomme_birlesen)
        con.commit()

        # 4) Birkaç ek birleştirme turu: bir birleşme sonrası merkez değişip başka bir eşleşmeyi
        # ortaya çıkarabilir (ör. A+B birleşince C de ona yaklaşabilir).
        if gom:
            for _ in range(5):
                uygulanan = gomme_ile_birlestir(con, ayar, gom, None, g=g)
                gomme_birlesen += len(uygulanan)
                if not uygulanan:
                    break

        # 5) Claude varsa: kalan diller arası birleştirme + özet
        if client is None:
            client = summarize.istemci()
        birlesen = ozetlenen = 0
        if client:
            if ayar.llm_birlestirme and getattr(client, "birlestirme", True):
                for zayif_id, guclu_id in summarize.birlestirme_onerileri(con, ayar, client, acilan_toplam):
                    hedef = cluster.kok_olay(con, guclu_id)
                    if hedef != cluster.kok_olay(con, zayif_id):
                        cluster.birlestir(con, hedef, zayif_id)
                        birlesen += 1
                con.commit()
            ozetlenen = summarize.ozetle(con, ayar, client)

        cluster.olay_sayaclarini_guncelle(con, eski_olaylar)  # artık boş kalanlar 0'a düşsün
        con.commit()

        # 6) Telegram bildirim takibini senkronla: aksi halde bir sonraki `dongu` turu, bu yeniden
        # gruplamanın yol açtığı ani kaynak sayısı sıçramasını organik "olay büyüyor" sanıp sahte
        # mesaj gönderebilir (ya da taban çok yüksek kalıp gerçek bir büyüme hiç bildirilmez).
        tasinan_bildirim = telegram.gecisleri_uygula(con, eski_yeni)

        n_olay = export.yaz(con, ayar)
        con.close()

        sonuc = dict(haber=len(pencere), silinen_gecersiz=len(gecersiz), silinen_tekrar=len(silinecek),
                     yeni_olay=len(acilan_toplam), gomme_birlesen=gomme_birlesen, llm_birlesen=birlesen,
                     ozetlenen=ozetlenen, tasinan_bildirim=tasinan_bildirim, n_olay=n_olay, yedek=str(yedek))
        log.info("yeniden-grupla: %d haber (%d geçersiz, %d tekrar silindi) · %d yeni olay · gömme ile"
                 " birleşen: %d · Claude ile birleşen: %d · özetlenen: %d · taşınan bildirim: %d"
                 " · dışa aktarılan olay: %d",
                 len(pencere), len(gecersiz), len(silinecek), len(acilan_toplam), gomme_birlesen,
                 birlesen, ozetlenen, tasinan_bildirim, n_olay)
        return sonuc


def feed_durum(ayar: Ayarlar):
    con = db.baglan(ayar.veritabani)
    satirlar = con.execute("SELECT * FROM feed_durum ORDER BY ardisik_hata DESC, ad").fetchall()
    for r in satirlar:
        durum = "OK " if r["ardisik_hata"] == 0 else f"HATA x{r['ardisik_hata']}"
        print(f"{durum:9} {r['ad']:32} öğe={r['son_oge']:<4} {r['hata'] or ''}")


def main():
    p = argparse.ArgumentParser(prog="collector")
    p.add_argument("komut", choices=["tur", "dongu", "feed-durum", "yeniden-grupla",
                                     "telegram-chat-id", "telegram-test"])
    p.add_argument("--aralik", type=int, default=300, help="dongu: turlar arası saniye")
    p.add_argument("--saat", type=int, help="yeniden-grupla: kaç saatlik pencere (varsayılan: export_saat)")
    p.add_argument("--kaynaklar", type=Path, help="sources.yaml yerine başka bir dosya")
    p.add_argument("--db", type=Path)
    p.add_argument("--cikti", type=Path)
    p.add_argument("--site", type=Path, nargs="?", const=KOK / "public",
                   help="her turdan sonra siteyi bu klasöre yeniden oluştur (varsayılan: public)")
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
    if a.komut == "yeniden-grupla":
        return yeniden_grupla(ayar, saat=a.saat)
    if a.komut == "telegram-chat-id":
        return telegram.chat_id_bul()
    if a.komut == "telegram-test":
        return telegram.test_mesaji()

    def tur_ve_site():
        tur(ayar)
        if a.site:
            from web.build import olustur
            olustur(ayar.cikti_klasoru / "events.json", a.site)

    if a.komut == "tur":
        return tur_ve_site()
    while True:
        try:
            tur_ve_site()
        except Exception:
            log.exception("tur başarısız; bir sonrakinde yeniden denenecek")
        time.sleep(a.aralik)


if __name__ == "__main__":
    main()
