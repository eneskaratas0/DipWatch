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

# Haber değil: kariyer/hakkımızda/abonelik/ekip gibi kurumsal sayfalar (başlık başıyla eşleşir,
# "jobs at risk..." ya da "AB üyelik müzakereleri" gibi gerçek haberleri yanlışlıkla elemesin diye
# hepsi ^ ile başa sabitlenmiş). TR kaynaklar da olduğu için Türkçe kalıpları da içerir.
_KURUMSAL = re.compile(
    r"^(careers?|jobs) at\b|^about us\b|^contact us\b|^advertise with us\b|"
    r"^subscri(be|ption)s?\b|^newsletter\b|^privacy policy\b|"
    r"^terms (of|and) (service|use)\b|^cookie policy\b|^site ?map\b|"
    r"^meet the team\b|^our team\b|"
    r"^abone ol|^bize ulaşın\b|^hakkımızda\b|^ileti[sş]im$|^gizlilik politikası\b|"
    r"^kullanım şartları\b|^reklam ver|^kariyer(imiz)?\b|^bizi takip edin\b",
    re.IGNORECASE)

# "JEDDAH/RIYADH: ARAB NEWS TEAM" gibi kısa, tamamen büyük harfli künye/dateline başlıkları.
_TUR_CANLI = re.compile(r"-\s*live\b|^live[\s:]", re.IGNORECASE)
_TUR_ANALIZ = re.compile(r"^(explainer|analysis|opinion|editorial)\b[\s:-]", re.IGNORECASE)
_NORM_TEMIZ = re.compile(r"[^a-zçğıöşü0-9 ]+")


def temizle(metin: str, uzunluk: int = 600) -> str:
    metin = html.unescape(_ETIKET.sub(" ", metin or ""))
    return re.sub(r"\s+", " ", metin).strip()[:uzunluk]


def gecersiz_baslik_mi(baslik: str) -> bool:
    """Haber değil: kariyer/hakkımızda/abonelik sayfaları ya da kısa, tamamen büyük harfli künye
    başlıkları ("JEDDAH/RIYADH: ARAB NEWS TEAM" gibi; Google News bu tür kurumsal sayfaları da
    site: sorgusuyla haber zannedip döndürebiliyor)."""
    if _KURUMSAL.search(baslik):
        return True
    harfler = [c for c in baslik if c.isalpha()]
    return bool(harfler) and len(baslik) < 60 and all(c.isupper() for c in harfler)


def baslik_normalle(baslik: str) -> str:
    """Aynı kaynaktan gelen yinelenen haberleri (ör. Google News'in aynı haberi farklı yönlendirme
    kimlikleriyle iki kez döndürmesi) yakalamak için küçük harf + noktalama arındırılmış başlık."""
    t = baslik.replace("İ", "i").lower().replace("ı", "i")
    return re.sub(r"\s+", " ", _NORM_TEMIZ.sub(" ", t)).strip()


def icerik_turu(baslik: str) -> str:
    """Başlık kalıbından içerik türü: 'canli' (live blog), 'analiz' (explainer/analysis/opinion/
    editorial) ya da düz 'haber'. Küme kaymasını önlemek için bu tür başlıklar tek başına yeni bir
    olay açmasın diye cluster.py'de daha gevşek bir eşikle mevcut olaya bağlanmaya çalışılır."""
    b = baslik.strip()
    if _TUR_CANLI.search(b):
        return "canli"
    if _TUR_ANALIZ.match(b):
        return "analiz"
    return "haber"


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

    haric_desen = re.compile("|".join(k.haric), re.IGNORECASE) if k.haric else None
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
        if gecersiz_baslik_mi(baslik) or (haric_desen and haric_desen.search(baslik)):
            continue
        haberler.append(dict(link=link_normalle(link), kaynak=kaynak_adi, bolge=k.bolge,
                             dil=k.dil, tur=k.tur, baslik=baslik, ozet=ozet, yayin=_tarih(e),
                             baslik_norm=baslik_normalle(baslik), icerik_turu=icerik_turu(baslik)))
    return k, haberler, None


def hepsini_cek(kaynaklar, paralel=16, zaman_asimi=20):
    with cf.ThreadPoolExecutor(paralel) as ex:
        return list(ex.map(lambda k: cek(k, zaman_asimi), kaynaklar))
