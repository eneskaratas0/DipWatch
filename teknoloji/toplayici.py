"""Teknoloji ve siber güvenlik haberlerini çeker, sınıflandırır, tekrarları ayıklar, SQLite'a yazar ve
site için data/teknoloji.json dosyasını üretir. Ana toplayıcıdan (collector) bağımsız çalışır; yalnızca
aynı veritabanı dosyasını (ayrı tablolarla) ve fetch.py'deki yardımcıları paylaşır."""
import concurrent.futures as cf
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

from collector import fetch
from collector.config import Kaynak

from . import kazi

log = logging.getLogger("dipwatch.teknoloji")
KATEGORILER = {"siber_guvenlik": "Siber güvenlik", "teknoloji": "Teknoloji"}

SEMA = """
CREATE TABLE IF NOT EXISTS tekno_haber (
    id INTEGER PRIMARY KEY,
    link TEXT UNIQUE,
    kaynak TEXT,
    kategori TEXT,                 -- 'siber_guvenlik' | 'teknoloji'
    baslik TEXT, baslik_norm TEXT,
    ozet TEXT,                     -- beslemedeki açıklamanın kısaltılmışı (kaynağın dilinde)
    yayin TEXT,                    -- ISO UTC
    eklenme TEXT,
    diger_kaynaklar TEXT DEFAULT '[]',  -- aynı haberi sonradan veren kaynaklar: [{kaynak, link, baslik}]
    vektor BLOB                    -- başlığın gömme vektörü (fastembed kuruluysa), bkz. _gomme_esi
);
CREATE INDEX IF NOT EXISTS tekno_haber_yayin ON tekno_haber(yayin);
CREATE INDEX IF NOT EXISTS tekno_haber_baslik ON tekno_haber(baslik_norm);

-- Tekrar sayılıp eklenmeyen haberlerin linkleri: sonraki turlarda (asıl haber pencereden çıksa bile)
-- yeniden değerlendirilip ayrı haber olarak eklenmesinler.
CREATE TABLE IF NOT EXISTS tekno_tekrar (
    link TEXT PRIMARY KEY,
    haber_id INTEGER REFERENCES tekno_haber(id)
);

CREATE TABLE IF NOT EXISTS tekno_kaynak_durum (
    ad TEXT PRIMARY KEY,
    son_deneme TEXT, son_basari TEXT,
    yontem TEXT,                   -- son başarılı yöntem: rss | kazi | google_news
    son_oge INTEGER DEFAULT 0,
    ardisik_hata INTEGER DEFAULT 0,
    hata TEXT
);
"""


@dataclass
class Ayar:
    kaynak_dosyasi: Path = Path(__file__).resolve().parent / "kaynaklar.yaml"
    tekrar_penceresi_saat: int = 48    # bu süre içinde aynı/çok benzer başlık tekrar sayılır
    benzerlik_orani: float = 0.6       # ortak kelime / kısa başlığın kelime sayısı (farklı kaynaklar arası)
    min_ortak_kelime: int = 3          # en az 2'si _GENEL dışında (konuya özgü: ürün, şirket, isim) olmalı
    gomme_esigi: float = 0.85          # fastembed varsa: farklı kaynaklar arası anlam benzerliği
    en_eski_gun: int = 30              # bundan eski haberler hiç eklenmez (beslemelerdeki eski yazılar)
    export_gun: int = 7                # sitede kaç günlük haber görünsün
    export_en_fazla: int = 800
    ozet_uzunluk: int = 280
    paralel: int = 8
    zaman_asimi: int = 20


@dataclass
class TeknoKaynak:
    ad: str
    kategori: str
    url: str
    yedekler: list = field(default_factory=list)
    haric: tuple = ()


def kaynaklari_yukle(yol: Path) -> list[TeknoKaynak]:
    veri = yaml.safe_load(open(yol, encoding="utf-8"))["kaynaklar"]
    return [TeknoKaynak(ad=s["ad"], kategori=s.get("kategori", "otomatik"), url=s["url"],
                        yedekler=list(s.get("yedekler") or ()), haric=tuple(s.get("haric") or ()))
            for s in veri if s.get("durum") != "kapali"]


# --- sınıflandırma -------------------------------------------------------------------------------

# Başlık/özet/etikette geçerse haber siber güvenlik sayılır ("otomatik" kategorili kaynaklarda).
_SIBER = re.compile(
    r"\b(cyber\w*|(?<!national )security|hack(s|ed|er|ers|ing)?|breach(es|ed)?|ransomware|malware|phishing|smishing|"
    r"vulnerabilit(y|ies)|exploit(s|ed|ing)?|zero[- ]day|0-day|cve-\d{4}-\d+|patch tuesday|botnets?|ddos|"
    r"spyware|stalkerware|trojans?|backdoors?|rootkits?|infostealers?|stealers?|apt\d+|threat actors?|"
    r"leak(s|ed)?|cybercrim\w*|extortion|espionage|scams?|fraud|crypto[- ]?theft|credential(s)?|"
    r"password(s)?|encryption|cisa|nsa|siber|fidye|kimlik avı|zararlı yazılım|güvenlik açığı|sızıntı)\b",
    re.IGNORECASE)


# Beslemenin kendi bölüm etiketleri (Ars Technica ve BleepingComputer "Security" kullanıyor); tam eşleşme.
_SIBER_ETIKET = re.compile(r"^(security|cyber ?security|hacking|ransomware|malware|data breach(es)?|"
                           r"vulnerabilit(y|ies)|privacy & security|siber güvenlik)$", re.IGNORECASE)


def siber_mi(*metinler: str) -> bool:
    return any(_SIBER.search(m or "") for m in metinler)


def kategori_belirle(k: TeknoKaynak, baslik: str, ozet: str, etiketler=()) -> str:
    if k.kategori in KATEGORILER:
        return k.kategori
    # Beslemede etiket varsa en güvenilir işaret odur: kelime taraması "Microsoft fixes Remote Desktop
    # failures" (Microsoft bölümü) gibi haberleri, özetteki bir "security update" yüzünden yanlış
    # sınıflıyordu. Etiket yoksa başlık + özetteki anahtar kelimelere bakılır.
    if etiketler:
        return "siber_guvenlik" if any(_SIBER_ETIKET.match(t.strip()) for t in etiketler) else "teknoloji"
    return "siber_guvenlik" if siber_mi(baslik, ozet) else "teknoloji"


# --- çekme ---------------------------------------------------------------------------------------

_KUYRUK = re.compile(r"\s*(The post .{0,300} appeared first on .*|\[\.\.\.\]|\[…\]|Continue reading.*|Read more.*)$",
                     re.IGNORECASE)


def ozet_kisalt(metin: str, uzunluk: int = 280) -> str:
    m = _KUYRUK.sub("", fetch.temizle(metin, 2000)).strip()
    if len(m) <= uzunluk:
        return m
    kes = m[:uzunluk].rsplit(" ", 1)[0].rstrip(",;:-")
    return kes + "…"


def _rss(k: TeknoKaynak, url: str, ayar: Ayar) -> list[dict]:
    f = feedparser.parse(fetch._indir(url, ayar.zaman_asimi))
    if not f.entries and f.bozo:
        raise ValueError(f"ayrıştırılamadı: {f.bozo_exception}")
    sonuc = []
    for e in f.entries:
        link, baslik = e.get("link"), fetch.temizle(e.get("title", ""), 300)
        if not link or not baslik:
            continue
        ozet = e.get("summary", "")
        etiketler = [t.get("term", "") for t in e.get("tags") or ()]
        sonuc.append(dict(link=link, baslik=baslik, ozet=ozet, yayin=fetch._tarih(e), etiketler=etiketler))
    return sonuc


def _google_news(k: TeknoKaynak, y: dict, ayar: Ayar) -> list[dict]:
    from collector.config import google_news_url
    gk = Kaynak(ad=k.ad, bolge="", url=google_news_url(y["alan_adi"], "en", y.get("gn_sure", "1d")),
                yontem="google_news")
    _, haberler, hata = fetch.cek(gk, ayar.zaman_asimi)
    if hata:
        raise RuntimeError(hata)
    return [dict(link=h["link"], baslik=h["baslik"], ozet="", yayin=h["yayin"], etiketler=[]) for h in haberler]


def _kazi(k: TeknoKaynak, y: dict, ayar: Ayar) -> list[dict]:
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return [dict(link=h["link"], baslik=h["baslik"], ozet="", yayin=h["yayin"] or simdi, etiketler=[])
            for h in kazi.kazi(y["url"], y["link_deseni"], ayar.zaman_asimi)]


def cek(k: TeknoKaynak, ayar: Ayar):
    """Kaynağın RSS'ini, olmazsa sırayla yedek yöntemlerini dener.
    (kaynak, haberler, kullanılan_yöntem, hata) döndürür; hata yalnızca HİÇBİR yöntem çalışmazsa dolu."""
    denemeler = [{"yontem": "rss", "url": k.url}] + k.yedekler
    hatalar = []
    for y in denemeler:
        try:
            if y["yontem"] == "rss":
                ham = _rss(k, y["url"], ayar)
            elif y["yontem"] == "google_news":
                ham = _google_news(k, y, ayar)
            elif y["yontem"] == "kazi":
                ham = _kazi(k, y, ayar)
            else:
                raise ValueError(f"bilinmeyen yöntem: {y['yontem']}")
        except Exception as ex:  # ağ, 403, ayrıştırma...
            hatalar.append(f"{y['yontem']}: {str(ex)[:120]}")
            continue
        if not ham:
            hatalar.append(f"{y['yontem']}: boş")
            continue
        return k, _normalle(k, ham, ayar), y["yontem"], None
    return k, [], None, " | ".join(hatalar)[:400]


def _normalle(k: TeknoKaynak, ham: list[dict], ayar: Ayar) -> list[dict]:
    haric = re.compile("|".join(k.haric), re.IGNORECASE) if k.haric else None
    simdi = datetime.now(timezone.utc)
    sinir = (simdi - timedelta(days=ayar.en_eski_gun)).isoformat()
    sonuc = []
    for h in ham:
        baslik = h["baslik"]
        if fetch.gecersiz_baslik_mi(baslik) or (haric and haric.search(baslik)):
            continue
        yayin = min(h["yayin"], simdi.isoformat(timespec="seconds"))  # gelecekteki tarihleri kırp
        if yayin < sinir:
            continue
        ozet = ozet_kisalt(h["ozet"], ayar.ozet_uzunluk)
        sonuc.append(dict(link=fetch.link_normalle(h["link"]), kaynak=k.ad, baslik=baslik,
                          baslik_norm=fetch.baslik_normalle(baslik), ozet=ozet, yayin=yayin,
                          kategori=kategori_belirle(k, baslik, ozet, h.get("etiketler") or ())))
    return sonuc


# --- tekrar ayıklama ------------------------------------------------------------------------------

_DOLGU = set("""the and for with from that this into over after amid about says said new how why what
when who are was were has have its their than more most just now out off can could will would may
bir ile ve için olan gibi daha çok""".split())
# Bu alandaki hemen her başlıkta geçen kelimeler (kök hâlleriyle, bkz. kelimeler()): ortak kelime oranına
# sayılır ama tek başına iki haberi "aynı" yapamaz -- "Oracle ... RCE Flaw Days After Security Patch" ile
# "Microsoft Patches More Than 1,400 Security Flaws" yalnızca patch/security/flaw paylaşıyor.
_GENEL = set("""hacker hack security secur flaw vulnerability vulnerabiliti bug patch fix attack attacker
exploit exploited critical malware ransomware data breach cyber cyberattack threat actor warn warns
user update target campaign new report researcher million billion""".split())


def kelimeler(baslik_norm: str) -> frozenset:
    """Başlığın anlamlı kelimeleri; kaba kök: sondaki -s/-es/-ed/-ing atılır (patches ~ patched ~ patch)."""
    sonuc = set()
    for w in baslik_norm.split():
        if len(w) < 3 or w in _DOLGU:
            continue
        for ek in ("ing", "es", "ed", "s"):
            if len(w) > len(ek) + 3 and w.endswith(ek):
                w = w[: -len(ek)]
                break
        sonuc.add(w)
    return frozenset(sonuc)


def benzer_mi(a: frozenset, b: frozenset, ayar: Ayar) -> bool:
    ortak = a & b
    return (len(ortak) >= ayar.min_ortak_kelime and len(ortak - _GENEL) >= 2
            and len(ortak) / max(1, min(len(a), len(b))) >= ayar.benzerlik_orani)


def tablo_hazirla(con):
    con.executescript(SEMA)


def kaydet(con, haberler: list[dict], ayar: Ayar, gom=None) -> tuple[int, int]:
    """Yeni haberleri ekler, tekrarları ayıklar. (eklenen, tekrar_sayilan) döndürür.

    Tekrar sayılanlar:
      1. aynı link (normalize edilmiş) -- daha önce ya da bu turda görülmüş;
      2. son `tekrar_penceresi_saat` içinde başka bir kaynaktan aynı normalize başlık; aynı kaynaktan
         ise yalnızca AYNI_KAYNAK_SAAT içinde (Google News'in aynı haberi iki linkle döndürmesi);
      3. aynı pencerede FARKLI bir kaynaktan çok benzer başlık (ortak kelime oranı) ya da, fastembed
         kuruluysa, anlamca çok yakın başlık (aynı haberin başka kelimelerle yazılmışı).
    Tekrar, ilk gelen haberin `diger_kaynaklar` listesine eklenir; sitede "Ayrıca:" olarak görünür.
    Aynı kaynağın benzer başlıkları (CISA'nın her gün "Adds Two Known Exploited Vulnerabilities to
    Catalog" duyurusu gibi) farklı linkli oldukça ayrı haber sayılır."""
    tablo_hazirla(con)
    simdi = datetime.now(timezone.utc)
    sinir = (simdi - timedelta(hours=ayar.tekrar_penceresi_saat)).isoformat()
    adaylar = [dict(r) for r in con.execute(
        """SELECT id, kaynak, baslik, baslik_norm, link, yayin, diger_kaynaklar, vektor FROM tekno_haber
           WHERE yayin >= ?""",
        (sinir,))]
    for a in adaylar:
        a["kelimeler"] = kelimeler(a["baslik_norm"])

    yeni = []
    gorulen_link = set()
    for h in sorted(haberler, key=lambda h: h["yayin"]):  # ilk yayımlayan "asıl" kaynak olsun
        if h["link"] in gorulen_link:
            continue
        gorulen_link.add(h["link"])
        if (con.execute("SELECT 1 FROM tekno_haber WHERE link=?", (h["link"],)).fetchone()
                or con.execute("SELECT 1 FROM tekno_tekrar WHERE link=?", (h["link"],)).fetchone()):
            continue
        yeni.append(h)

    vektorler = {}
    if gom is not None and yeni:
        import numpy as np
        eksik = [a for a in adaylar if a["vektor"] is None]
        for a, v in zip(eksik, gom([a["baslik"] for a in eksik]) if eksik else ()):
            a["vektor"] = v.astype(np.float32).tobytes()
            con.execute("UPDATE tekno_haber SET vektor=? WHERE id=?", (a["vektor"], a["id"]))
        for h, v in zip(yeni, gom([h["baslik"] for h in yeni])):
            vektorler[h["link"]] = v.astype(np.float32)

    eklenen = tekrar = 0
    eklenme = simdi.isoformat(timespec="seconds")
    for h in yeni:
        kel = kelimeler(h["baslik_norm"])
        v = vektorler.get(h["link"])
        asil = next((a for a in adaylar if a["baslik_norm"] == h["baslik_norm"]
                     and (a["kaynak"] != h["kaynak"] or _saat_farki(a["yayin"], h["yayin"]) < AYNI_KAYNAK_SAAT)),
                    None)
        if asil is None:
            asil = next((a for a in adaylar if a["kaynak"] != h["kaynak"] and benzer_mi(kel, a["kelimeler"], ayar)),
                        None)
        if asil is None and v is not None:
            asil = _gomme_esi(v, h, adaylar, ayar)
        if asil is not None:
            tekrar += 1
            con.execute("INSERT OR IGNORE INTO tekno_tekrar (link, haber_id) VALUES (?,?)", (h["link"], asil["id"]))
            digerleri = json.loads(asil["diger_kaynaklar"] or "[]")
            if h["kaynak"] != asil["kaynak"] and all(d["kaynak"] != h["kaynak"] for d in digerleri):
                digerleri.append({"kaynak": h["kaynak"], "link": h["link"], "baslik": h["baslik"]})
                asil["diger_kaynaklar"] = json.dumps(digerleri, ensure_ascii=False)
                con.execute("UPDATE tekno_haber SET diger_kaynaklar=? WHERE id=?",
                            (asil["diger_kaynaklar"], asil["id"]))
            log.debug("tekrar: [%s] %s  ~  [%s] %s", h["kaynak"], h["baslik"], asil["kaynak"], asil["baslik"])
            continue
        vb = v.tobytes() if v is not None else None
        cur = con.execute(
            """INSERT INTO tekno_haber (link, kaynak, kategori, baslik, baslik_norm, ozet, yayin, eklenme, vektor)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (h["link"], h["kaynak"], h["kategori"], h["baslik"], h["baslik_norm"], h["ozet"], h["yayin"],
             eklenme, vb))
        adaylar.append({"id": cur.lastrowid, "kaynak": h["kaynak"], "baslik": h["baslik"],
                        "baslik_norm": h["baslik_norm"], "link": h["link"], "yayin": h["yayin"], "diger_kaynaklar": "[]",
                        "vektor": vb, "kelimeler": kel})
        eklenen += 1
    con.commit()
    return eklenen, tekrar


AYNI_KAYNAK_SAAT = 12


def _saat_farki(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def _gomme_esi(v, h, adaylar, ayar):
    import numpy as np
    en_iyi, en_iyi_benz = None, ayar.gomme_esigi
    for a in adaylar:
        if a["kaynak"] == h["kaynak"] or a["vektor"] is None:
            continue
        benz = float(np.dot(v, np.frombuffer(a["vektor"], dtype=np.float32)))
        if benz >= en_iyi_benz:
            en_iyi, en_iyi_benz = a, benz
    return en_iyi


# --- dışa aktarma ve tur --------------------------------------------------------------------------

def durum_yaz(con, k, n, yontem, hata):
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if hata:
        con.execute("""INSERT INTO tekno_kaynak_durum (ad, son_deneme, ardisik_hata, hata) VALUES (?,?,1,?)
                       ON CONFLICT(ad) DO UPDATE SET son_deneme=excluded.son_deneme,
                       ardisik_hata=ardisik_hata+1, hata=excluded.hata""", (k.ad, simdi, hata))
    else:
        con.execute("""INSERT INTO tekno_kaynak_durum (ad, son_deneme, son_basari, yontem, son_oge)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(ad) DO UPDATE SET son_deneme=excluded.son_deneme, son_basari=excluded.son_basari,
                       yontem=excluded.yontem, son_oge=excluded.son_oge, ardisik_hata=0, hata=NULL""",
                    (k.ad, simdi, simdi, yontem, n))


def disa_aktar(con, yol: Path, ayar: Ayar, kaynak_adlari: list[str]) -> int:
    """Son `export_gun` günün haberleri, en yeni en üstte."""
    sinir = (datetime.now(timezone.utc) - timedelta(days=ayar.export_gun)).isoformat()
    satirlar = con.execute(
        """SELECT id, baslik, kaynak, yayin, link, ozet, kategori, diger_kaynaklar FROM tekno_haber
           WHERE yayin >= ? ORDER BY yayin DESC, id DESC LIMIT ?""", (sinir, ayar.export_en_fazla)).fetchall()
    haberler = [{**dict(r), "diger_kaynaklar": json.loads(r["diger_kaynaklar"] or "[]")} for r in satirlar]
    veri = {"olusturulma": datetime.now(timezone.utc).isoformat(timespec="seconds"), "gun": ayar.export_gun,
            "kaynaklar": kaynak_adlari, "kategoriler": KATEGORILER, "haberler": haberler}
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(yol)
    return len(haberler)


def tur(con, ayar: Ayar, cikti: Path, gom=None) -> dict:
    tablo_hazirla(con)
    kaynaklar = kaynaklari_yukle(ayar.kaynak_dosyasi)
    with cf.ThreadPoolExecutor(ayar.paralel) as ex:
        sonuclar = list(ex.map(lambda k: cek(k, ayar), kaynaklar))
    tum = []
    for k, haberler, yontem, hata in sonuclar:
        durum_yaz(con, k, len(haberler), yontem, hata)
        if hata:
            log.warning("%s: hiçbir yöntem çalışmadı: %s", k.ad, hata)
        elif yontem != "rss":
            log.info("%s: RSS çalışmadı, %s ile çekildi", k.ad, yontem)
        tum.extend(haberler)
    con.commit()
    eklenen, tekrar = kaydet(con, tum, ayar, gom)
    n = disa_aktar(con, cikti, ayar, [k.ad for k in kaynaklar])
    calisan = sum(1 for s in sonuclar if not s[3])
    log.info("teknoloji: kaynak %d/%d çalıştı · çekilen: %d · yeni: %d · tekrar: %d · sitede: %d",
             calisan, len(sonuclar), len(tum), eklenen, tekrar, n)
    return dict(kaynak=len(sonuclar), calisan=calisan, cekilen=len(tum), yeni=eklenen, tekrar=tekrar, sitede=n)
