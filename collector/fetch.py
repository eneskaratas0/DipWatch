"""RSS/Atom beslemelerini paralel çeker, haberleri normalleştirir."""
import concurrent.futures as cf
import html
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from .config import Kaynak

UA = "Mozilla/5.0 (compatible; DipWatch/0.2; +haber-izleme)"
_ETIKET = re.compile(r"<[^>]+>")
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


def cek(k: Kaynak, zaman_asimi: int = 20):
    """(kaynak, haberler, hata) döndürür."""
    try:
        req = urllib.request.Request(k.url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=zaman_asimi) as r:
            govde = r.read(3_000_000)
        f = feedparser.parse(govde)
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
            if yayin and baslik.endswith(" - " + yayin):
                baslik = baslik[: -len(yayin) - 3]
            ozet = ""  # GN açıklaması yalnızca başlığın tekrarı
        else:
            ozet = temizle(e.get("summary", ""))
        haberler.append(dict(link=link_normalle(link), kaynak=kaynak_adi, bolge=k.bolge,
                             dil=k.dil, tur=k.tur, baslik=baslik, ozet=ozet, yayin=_tarih(e)))
    return k, haberler, None


def hepsini_cek(kaynaklar, paralel=16, zaman_asimi=20):
    with cf.ThreadPoolExecutor(paralel) as ex:
        return list(ex.map(lambda k: cek(k, zaman_asimi), kaynaklar))
