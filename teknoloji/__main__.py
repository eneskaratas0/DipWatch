"""DipWatch teknoloji ve siber güvenlik bölümü.

Kullanım:
  python -m teknoloji tur                  # bir kez çek, tekrarları ayıkla, data/teknoloji.json yaz
  python -m teknoloji dongu --aralik 3600  # her saat bir tur
  python -m teknoloji durum                # hangi kaynak çalışıyor, hangi yöntemle (rss/kazi/google_news)
  --site eklenirse her turdan sonra public/teknoloji.html de yeniden oluşturulur.
"""
import argparse
import logging
import time
from pathlib import Path

from collector import db
from collector.config import KOK, Ayarlar

from . import toplayici

log = logging.getLogger("dipwatch.teknoloji")


def _gomucu():
    """Ana toplayıcının çok dilli gömme modeli kuruluysa (fastembed) farklı kelimelerle yazılmış aynı haberi
    yakalamak için kullanılır; yoksa yalnızca link/başlık/kelime benzerliğiyle ayıklanır."""
    try:
        from collector import embed
        return embed.gomucu(Ayarlar())
    except ImportError:
        return None


def durum(veritabani: Path):
    con = db.baglan(veritabani)
    toplayici.tablo_hazirla(con)
    for r in con.execute("SELECT * FROM tekno_kaynak_durum ORDER BY ardisik_hata DESC, ad"):
        d = "OK " if r["ardisik_hata"] == 0 else f"HATA x{r['ardisik_hata']}"
        print(f"{d:9} {r['ad']:20} yöntem={r['yontem'] or '-':12} öğe={r['son_oge']:<4} {r['hata'] or ''}")


def main():
    p = argparse.ArgumentParser(prog="teknoloji")
    p.add_argument("komut", choices=["tur", "dongu", "durum"])
    p.add_argument("--aralik", type=int, default=3600, help="dongu: turlar arası saniye (varsayılan 1 saat)")
    p.add_argument("--kaynaklar", type=Path, help="teknoloji/kaynaklar.yaml yerine başka bir dosya")
    p.add_argument("--db", type=Path, default=Ayarlar().veritabani)
    p.add_argument("--cikti", type=Path, default=KOK / "data" / "teknoloji.json")
    p.add_argument("--site", type=Path, nargs="?", const=KOK / "public",
                   help="her turdan sonra teknoloji sayfasını bu klasöre yeniden oluştur (varsayılan: public)")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.komut == "durum":
        return durum(a.db)
    ayar = toplayici.Ayar()
    if a.kaynaklar:
        ayar.kaynak_dosyasi = a.kaynaklar
    gom = _gomucu()

    def bir_tur():
        con = db.baglan(a.db)
        try:
            toplayici.tur(con, ayar, a.cikti, gom)
        finally:
            con.close()
        if a.site:
            from web.teknoloji import yaz
            yaz(a.cikti, a.site)

    if a.komut == "tur":
        return bir_tur()
    while True:
        try:
            bir_tur()
        except Exception:
            log.exception("teknoloji turu başarısız; bir sonrakinde yeniden denenecek")
        time.sleep(a.aralik)


if __name__ == "__main__":
    main()
