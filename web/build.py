"""events.json -> statik site (yalnızca standart kütüphane, API anahtarı gerekmez).

Çıktı:
  index.html            tüm olaylar, güne göre gruplu
  bolge/<bolge>.html    bir bölgenin olayları, güne göre gruplu
  olay/<id>.html        olay sayfası: özet/başlık, zaman çizelgesi, tüm kaynak linkleri
  stil.css, filtre.js
Linkler göreli olduğu için site hem dosyadan (file://) hem bir alt klasörden (GitHub Pages) açılır.
"""
import json
import logging
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

KOK = Path(__file__).resolve().parent.parent
STATIK = Path(__file__).resolve().parent / "statik"
SAAT_DILIMI = ZoneInfo("Europe/Istanbul")
log = logging.getLogger("dipwatch.web")

# Sıra, menüdeki sıradır. Toplayıcının ve Claude özetinin kullandığı anahtarlar.
BOLGE_ADLARI = {
    "orta_dogu": "Orta Doğu",
    "rusya_ukrayna_kafkasya": "Rusya, Ukrayna, Kafkasya",
    "avrupa": "Avrupa",
    "asya_pasifik": "Asya-Pasifik",
    "afrika": "Afrika",
    "amerika": "Amerika",
    "turkiye": "Türkiye",
    "kuresel": "Küresel",
}
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
         "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
DILLER = {"tr": "TR", "en": "EN", "ar": "AR", "fr": "FR", "de": "DE", "ru": "RU", "fa": "FA", "he": "HE"}


def zaman(s):
    """ISO metni -> İstanbul saatinde datetime. Boş/bozuksa None."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(SAAT_DILIMI)


def gun_adi(d):
    return f"{d.day} {AYLAR[d.month - 1]} {d.year}, {GUNLER[d.weekday()]}"


def saat_dk(d):
    return d.strftime("%H:%M") if d else ""


def tarih_saat(d):
    return f"{d.day} {AYLAR[d.month - 1]} {d.strftime('%H:%M')}" if d else ""


def bolge_adi(b):
    return BOLGE_ADLARI.get(b, b.replace("_", " ").title())


def guvenli_link(url):
    """Yalnızca http(s) linklerini dışarı ver; javascript: vb. linkleri boşa çevir."""
    return url if urlparse(url or "").scheme in ("http", "https") else "#"


def sayfa(baslik, govde, kok="", aciklama="DipWatch: uluslararası siyaset olay takibi"):
    e = escape
    menu = "".join(f'<a href="{kok}bolge/{b}.html">{e(ad)}</a>' for b, ad in BOLGE_ADLARI.items())
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(baslik)}</title>
<meta name="description" content="{e(aciklama)}">
<link rel="stylesheet" href="{kok}stil.css">
</head>
<body>
<header class="ust">
  <a class="logo" href="{kok}index.html">DipWatch</a>
  <nav class="bolgeler"><a href="{kok}index.html">Tümü</a>{menu}</nav>
</header>
<main>
{govde}
</main>
<footer>Başlıklar ve linkler kaynakların kendisine aittir. DipWatch haberleri otomatik toplar ve gruplar;
özetler hata içerebilir, her zaman kaynağa bakın.</footer>
<script src="{kok}filtre.js"></script>
</body>
</html>
"""


def olay_karti(o, kok):
    e = escape
    son = zaman(o["son_haber"])
    rozetler = [f'<a class="rozet bolge" href="{kok}bolge/{e(o["bolge"])}.html">{e(bolge_adi(o["bolge"]))}</a>',
                f'<span class="rozet">{o["kaynak_sayisi"]} kaynak</span>']
    if o.get("onem"):
        rozetler.append(f'<span class="rozet onem" title="önem {o["onem"]}/5">{"★" * o["onem"]}</span>')
    ozet = f'<p class="ozet">{e(o["ozet"])}</p>' if o.get("ozet") else ""
    sinif = "olay tek" if o["kaynak_sayisi"] < 2 else "olay"
    return (f'<li class="{sinif}" data-ara="{e(arama_metni(o))}">'
            f'<a class="baslik" href="{kok}olay/{o["id"]}.html">{e(o["baslik"])}</a>'
            f'<div class="meta"><time>{saat_dk(son)}</time>{"".join(rozetler)}</div>{ozet}</li>')


def arama_metni(o):
    parcalar = [o["baslik"], o.get("ozet") or "", " ".join(o.get("ulkeler") or []),
                " ".join(o.get("etiketler") or [])] + [k["baslik"] for k in o["kaynaklar"]]
    # filtre.js ile aynı sadeleştirme: büyük/küçük harf ve ı/i farkı aramayı bozmasın
    return " ".join(parcalar).lower().replace("\u0307", "").replace("ı", "i")


def gunlere_bol(olaylar):
    """Olayları son haberin İstanbul tarihine göre gruplar; günler yeniden eskiye."""
    gunler = defaultdict(list)
    for o in olaylar:
        d = zaman(o["son_haber"])
        if d:
            gunler[d.date()].append(o)
    sirali = sorted(gunler.items(), reverse=True)
    for _, liste in sirali:
        # önem ve kaynak sayısı çok olan üstte; eşitlikte en yeni üstte
        liste.sort(key=lambda o: o["son_haber"], reverse=True)
        liste.sort(key=lambda o: (-(o.get("onem") or 0), -o["kaynak_sayisi"]))
    return sirali


def liste_sayfasi(baslik, alt, olaylar, kok, olusturulma):
    e = escape
    gunler = gunlere_bol(olaylar)
    cok = sum(1 for o in olaylar if o["kaynak_sayisi"] >= 2)
    atla = "".join(f'<a href="#g{g.isoformat()}">{g.day} {AYLAR[g.month - 1]}</a>' for g, _ in gunler)
    bolumler = []
    for g, liste in gunler:
        kartlar = "".join(olay_karti(o, kok) for o in liste)
        bolumler.append(f'<section class="gun" id="g{g.isoformat()}"><h2>{gun_adi(g)}</h2>'
                        f'<ul class="olaylar">{kartlar}</ul></section>')
    bos = '<p class="bos">Bu listede henüz olay yok.</p>' if not olaylar else ""
    govde = f"""<div class="sayfa-bas">
  <h1>{e(baslik)}</h1>
  <p class="alt">{e(alt)} · {len(olaylar)} olay, {cok} tanesi birden fazla kaynakta ·
  güncelleme: {tarih_saat(zaman(olusturulma))}</p>
  <div class="araclar">
    <input type="search" id="ara" placeholder="Başlık, ülke veya kaynakta ara" aria-label="Ara">
    <label><input type="checkbox" id="tek"> Tek kaynaklı olayları da göster</label>
  </div>
  <nav class="gunler">{atla}</nav>
</div>
{bos}{"".join(bolumler)}
<p class="bos" id="sonuc-yok" hidden>Filtreye uyan olay yok.</p>"""
    return sayfa(f"{baslik} · DipWatch", govde, kok)


def olay_sayfasi(o, kok="../"):
    e = escape
    ilk, son = zaman(o["ilk_haber"]), zaman(o["son_haber"])
    kaynaklar = sorted(o["kaynaklar"], key=lambda k: k.get("yayin") or "")

    if o.get("ozet"):
        ozet = f'<p class="ozet buyuk">{e(o["ozet"])}</p>'
    else:
        ozet = ('<p class="not">Bu olay için henüz Türkçe özet yok; başlık kaynaklardan birinden alındı. '
                'Ayrıntı için aşağıdaki kaynaklara bakın.</p>')

    etiketler = "".join(f'<span class="rozet">{e(x)}</span>' for x in (o.get("ulkeler") or []) + (o.get("etiketler") or []))

    cizelge, onceki_gun = [], None
    for k in kaynaklar:
        d = zaman(k.get("yayin"))
        if d and d.date() != onceki_gun:
            cizelge.append(f'<li class="cizelge-gun">{gun_adi(d.date())}</li>')
            onceki_gun = d.date()
        dil = DILLER.get(k.get("dil"), (k.get("dil") or "").upper())
        cizelge.append(
            f'<li><time>{saat_dk(d)}</time><div><span class="kaynak">{e(k["kaynak"])}</span>'
            f'<span class="dil">{e(dil)}</span><br>'
            f'<a href="{e(guvenli_link(k["link"]))}" rel="noopener noreferrer" target="_blank">{e(k["baslik"])}</a>'
            f'</div></li>')

    yayinlar = defaultdict(list)
    for k in kaynaklar:
        yayinlar[k["kaynak"]].append(k)
    kaynak_listesi = "".join(
        f'<li><strong>{e(ad)}</strong> ({len(liste)})<ul>'
        + "".join(f'<li><a href="{e(guvenli_link(k["link"]))}" rel="noopener noreferrer" target="_blank">'
                  f'{e(k["baslik"])}</a></li>' for k in liste)
        + "</ul></li>"
        for ad, liste in sorted(yayinlar.items(), key=lambda x: x[0].lower()))

    onem = f' · önem {"★" * o["onem"]}' if o.get("onem") else ""
    govde = f"""<article class="olay-sayfa">
  <p class="ust-bilgi"><a href="{kok}bolge/{e(o["bolge"])}.html">{e(bolge_adi(o["bolge"]))}</a> ·
  {o["kaynak_sayisi"]} kaynak, {len(kaynaklar)} haber{onem}</p>
  <h1>{e(o["baslik"])}</h1>
  <p class="alt">İlk haber: {tarih_saat(ilk)} · Son haber: {tarih_saat(son)} (İstanbul saati)</p>
  {ozet}
  <div class="etiketler">{etiketler}</div>
  <h2>Zaman çizelgesi</h2>
  <ol class="cizelge">{"".join(cizelge)}</ol>
  <h2>Tüm kaynaklar</h2>
  <ul class="kaynaklar">{kaynak_listesi}</ul>
</article>"""
    return sayfa(f"{o['baslik']} · DipWatch", govde, kok, aciklama=(o.get("ozet") or o["baslik"])[:200])


def olustur(girdi: Path, cikti: Path) -> int:
    veri = json.loads(girdi.read_text(encoding="utf-8"))
    olaylar = veri["olaylar"]
    olusturulma = veri.get("olusturulma")

    # Süresi dolan olayların sayfaları kalmasın diye olay/ ve bolge/ her seferinde baştan yazılır.
    # Klasörün geri kalanına dokunulmaz (yanlışlıkla başka bir klasör verilirse içi silinmesin).
    for alt in ("olay", "bolge"):
        shutil.rmtree(cikti / alt, ignore_errors=True)
        (cikti / alt).mkdir(parents=True)
    for dosya in STATIK.iterdir():
        shutil.copy(dosya, cikti / dosya.name)

    (cikti / "index.html").write_text(
        liste_sayfasi("Son olaylar", "Tüm bölgeler", olaylar, "", olusturulma), encoding="utf-8")
    bolgeye_gore = defaultdict(list)
    for o in olaylar:
        bolgeye_gore[o["bolge"]].append(o)
    for b in set(BOLGE_ADLARI) | set(bolgeye_gore):
        (cikti / "bolge" / f"{b}.html").write_text(
            liste_sayfasi(bolge_adi(b), "Bölge", bolgeye_gore.get(b, []), "../", olusturulma), encoding="utf-8")
    for o in olaylar:
        (cikti / "olay" / f"{o['id']}.html").write_text(olay_sayfasi(o), encoding="utf-8")

    log.info("site oluşturuldu: %s · %d olay · %d bölge", cikti, len(olaylar), len(bolgeye_gore))
    return len(olaylar)
