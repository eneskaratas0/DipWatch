"""LLM kotası dolduğunda yedek: olayın temsilci haberini ücretsiz çeviri servisleriyle Türkçeye çevirir.

Bu gerçek bir özet değildir (kaynakları karşılaştırmaz, bölge/önem vermez); yalnızca olay listesinde
yabancı dilde başlık yerine Türkçe başlık ve kısa açıklama görünsün diye vardır. LLM yeniden
kullanılabilir olunca ozetle() bu olayları zaten yeniden özetler ve çeviriyi ezer.

Servisler sırayla denenir; kota/engel (429, 403, Google'ın "sorry" sayfası) gelen servis bir süre
dinlendirilir ve sıradakine geçilir:
  1. Google Translate (anahtarsız, resmî olmayan uç; sunuculardan sık engellenir, ev bağlantısında çalışır)
  2. DeepL Free (DEEPL_API_KEY varsa; ayda 500.000 karakter)
  3. MyMemory (anahtarsız günde ~5.000 karakter; MYMEMORY_EMAIL yazılırsa ~50.000)
"""
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("dipwatch.ceviri")

_DINLEN_SANIYE = 3600
_dinlen: dict[str, float] = {}


class Engellendi(Exception):
    """Servis kota/engel bildirdi: bir süre kullanılmasın."""


def _getir(istek, zaman_asimi=20):
    try:
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as r:
            if "/sorry" in r.geturl():
                raise Engellendi("Google robot denetimi")
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 456):  # 456: DeepL kota doldu
            raise Engellendi(f"HTTP {e.code}")
        raise


def _google(metin, kaynak_dil):
    q = urllib.parse.urlencode({"client": "gtx", "sl": kaynak_dil or "auto", "tl": "tr", "dt": "t", "q": metin})
    istek = urllib.request.Request("https://translate.googleapis.com/translate_a/single?" + q,
                                   headers={"User-Agent": "Mozilla/5.0"})
    veri = _getir(istek)
    return "".join(parca[0] for parca in veri[0] if parca and parca[0])


def _deepl(metin, kaynak_dil):
    anahtar = os.environ.get("DEEPL_API_KEY")
    if not anahtar:
        return None
    govde = {"text": [metin], "target_lang": "TR"}
    if kaynak_dil:
        govde["source_lang"] = kaynak_dil.upper()
    istek = urllib.request.Request(
        "https://api-free.deepl.com/v2/translate", data=json.dumps(govde).encode(), method="POST",
        headers={"Authorization": f"DeepL-Auth-Key {anahtar}", "Content-Type": "application/json"})
    return _getir(istek)["translations"][0]["text"]


def _mymemory(metin, kaynak_dil):
    parametre = {"q": metin[:450], "langpair": f"{kaynak_dil or 'en'}|tr"}  # tek istekte en fazla 500 bayt
    if os.environ.get("MYMEMORY_EMAIL"):
        parametre["de"] = os.environ["MYMEMORY_EMAIL"]
    veri = _getir(urllib.request.Request(
        "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(parametre)))
    if veri.get("quotaFinished") or veri.get("responseStatus") == 429:
        raise Engellendi("günlük kota doldu")
    if veri.get("responseStatus") != 200:
        return None
    return veri["responseData"]["translatedText"]


SERVISLER = [("google", _google), ("deepl", _deepl), ("mymemory", _mymemory)]


def cevir(metin: str, kaynak_dil: str = "") -> str | None:
    """Metni Türkçeye çevirir; hiçbir servis çeviremezse None."""
    if not metin.strip():
        return metin
    for ad, fonksiyon in SERVISLER:
        if time.time() < _dinlen.get(ad, 0):
            continue
        try:
            sonuc = fonksiyon(metin, kaynak_dil)
        except Engellendi as e:
            _dinlen[ad] = time.time() + _DINLEN_SANIYE
            log.warning("çeviri: %s kullanılamıyor (%s); 1 saat dinlendiriliyor", ad, e)
            continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            log.warning("çeviri: %s hatası: %s", ad, e)
            continue
        if sonuc:
            return sonuc.strip()
    return None


def ceviriyle_doldur(con, ayar, baslik_sec) -> int:
    """Türkçe özeti hiç olmayan (ve daha önce çevrilmemiş) olaylara temsilci haberin Türkçe başlığını/açıklamasını yazar.
    Türkçe haberi olan olaylarda çeviri gerekmez; o haber doğrudan kullanılır. ozet_haber_sayisi
    değiştirilmez, böylece LLM yeniden çalışınca bu olayları gerçek özetle değiştirir."""
    olaylar = con.execute(
        """SELECT id FROM olay WHERE birlesti IS NULL AND kaynak_sayisi >= ?
             AND tr_ozet IS NULL AND ozet_turu IS NULL
           ORDER BY kaynak_sayisi DESC, guncelleme DESC LIMIT ?""",
        (ayar.ozet_min_kaynak, ayar.ceviri_max_olay_tur)).fetchall()
    n = 0
    for o in olaylar:
        haberler = [dict(r) for r in con.execute(
            "SELECT dil, baslik, ozet, icerik_turu, vektor FROM haber WHERE olay_id=? ORDER BY yayin", (o["id"],))]
        secilen = baslik_sec(haberler)
        h = next(x for x in haberler if x["baslik"] == secilen)
        aciklama = h["ozet"] if h["ozet"] and h["ozet"] != h["baslik"] else ""
        if h["dil"] == "tr":
            baslik, ozet = h["baslik"], aciklama
        else:
            baslik = cevir(h["baslik"], h["dil"])
            if baslik is None:
                break  # tüm servisler dinlenmede: bu tur bırak
            ozet = (cevir(aciklama[:450], h["dil"]) or "") if aciklama else ""
        con.execute("UPDATE olay SET tr_baslik=?, tr_ozet=?, ozet_turu='ceviri' WHERE id=?",
                    (baslik, ozet or None, o["id"]))
        con.commit()
        n += 1
    return n
