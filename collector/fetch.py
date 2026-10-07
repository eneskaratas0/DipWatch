"""RSS/Atom beslemelerini paralel çeker, haberleri normalleştirir."""
import concurrent.futures as cf
import html
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from .config import Kaynak

UA = "Mozilla/5.0 (compatible; DipWatch/0.2; +haber-izleme)"
_ETIKET = re.compile(r"<[^>]+>")
GN_MIN_KELIME = 4
_IZLEME = re.compile(r"^(utm_|fbclid|gclid|at_|cmpid|ocid)")


def temizle(metin: str, uzunluk: int = 600) -> str:
    metin = html.unescape(_ETIKET.sub(" ", metin or ""))
    return re.sub(r"\s+", " ", metin).strip()[:uzunluk]


def link_normalle(link: str) -> str:
    p = urlsplit(link.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not _IZLEME.match(k)]
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))


def _tarih(e) -> str:
    t = e.get("published_parsed") or e.get("updated_parsed")
    d = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
    return d.isoformat(timespec="seconds")


def _indir(url: str, zaman_asimi: int, deneme: int = 2) -> bytes:
    """Bağlantı sıfırlanması gibi geçici hatalarda bir kez daha dener (ör. aa.com.tr)."""
    for i in range(deneme):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=zaman_asimi) as r:
                return r.read(3_000_000)
        except urllib.error.HTTPError:
            raise  # 403/404 tekrar denemekle düzelmez
        except OSError:
            if i == deneme - 1:
                raise
            time.sleep(2)


def cek(k: Kaynak, zaman_asimi: int = 20):
    """(kaynak, haberler, hata) döndürür."""
    try:
        f = feedparser.parse(_indir(k.url, zaman_asimi))
        if not f.entries and f.bozo:
            return k, [], f"ayrıştırılamadı: {f.bozo_exception}"[:200]
    except Exception as ex:  # ağ, 403, zaman aşımı...
        return k, [], str(ex)[:200]

    haberler = []
    for e in f.entries:
        link, baslik = e.get("link"), temizle(e.get("title", ""), 300)
        if not link or not baslik:
            continue
        kaynak_adi = k.ad
        if k.yontem == "google_news":
            # Google News başlıkları "Başlık - Yayın" biçiminde gelir
            yayin = (e.get("source") or {}).get("title")
            # etiket sayfalarında ek iki kez gelebilir: "decentralization - Daily Sabah - Daily Sabah"
            # başlıksız sayfalar yalnızca "- Yayın" olarak gelir; baştaki boşluk onu da yakalar
            baslik = " " + baslik
            while yayin and baslik.endswith(" - " + yayin):
                baslik = baslik[: -len(yayin) - 3]
            baslik = baslik.strip()
            # site: sorgusu yazar, etiket ve bölüm sayfalarını da döndürür ("Energy", "Haaretz Cartoon")
            if len(baslik.split()) < GN_MIN_KELIME:
                continue
            ozet = ""  # GN açıklaması yalnızca başlığın tekrarı
        else:
            ozet = temizle(e.get("summary", ""))
        haberler.append(dict(link=link_normalle(link), kaynak=kaynak_adi, bolge=k.bolge,
                             dil=k.dil, tur=k.tur, baslik=baslik, ozet=ozet, yayin=_tarih(e)))
    return k, haberler, None


def hepsini_cek(kaynaklar, paralel=16, zaman_asimi=20):
    with cf.ThreadPoolExecutor(paralel) as ex:
        return list(ex.map(lambda k: cek(k, zaman_asimi), kaynaklar))
