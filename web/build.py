"""events.json -> statik site (yalnızca standart kütüphane, API anahtarı gerekmez).

Çıktı:
  index.html            tüm olaylar, güne göre gruplu
  bolge/<bolge>.html    bir bölgenin olayları, güne göre gruplu
  olay/<id>.html        olay sayfası: özet/başlık, zaman çizelgesi, tüm kaynak linkleri
  stil.css, filtre.js
Linkler göreli olduğu için site hem dosyadan (file://) hem bir alt klasörden (GitHub Pages) açılır.
"""
import base64
import json
import logging
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
# Bölge şeridi, dar kutulara sığdığı için tam adın kısaltıldığı yerler (ör. "Rusya, Ukrayna,
# Kafkasya" kutuda "Rusya, U…" diye kesiliyordu). Tam ad başka her yerde (menü, title, aria-label) kalır.
KISA_BOLGE_ADLARI = {"rusya_ukrayna_kafkasya": "Rusya-Ukrayna"}
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
         "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
DILLER = {"tr": "TR", "en": "EN", "ar": "AR", "fr": "FR", "de": "DE", "ru": "RU", "fa": "FA", "he": "HE"}
# "haber" için rozet gösterilmez (varsayılan, görsel gürültü eklemesin); bkz. collector/fetch.icerik_turu
TUR_ETIKETLERI = {"analiz": "Analiz", "canli": "Canlı"}


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


def bolge_adi_kisa(b):
    return KISA_BOLGE_ADLARI.get(b, bolge_adi(b))


def liste_href(kok, secili):
    return f"{kok}index.html" if not secili else f"{kok}bolge/{secili}.html"


def arsiv_href(kok, secili):
    return f"{kok}tek-kaynakli.html" if not secili else f"{kok}bolge/{secili}-tek.html"


def guvenli_link(url):
    """Yalnızca http(s) linklerini dışarı ver; javascript: vb. linkleri boşa çevir."""
    return url if urlparse(url or "").scheme in ("http", "https") else "#"


FONTLAR = ("https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600"
          "&family=Public+Sans:wght@400;500;600&display=swap")

# Mühür: --muhur rengiyle aynı, kâğıt zemin üstünde bir damga. Karanlık modu da izler.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<style>.p{fill:#f1f3f2}.i{fill:#1d4e89}'
    '@media (prefers-color-scheme:dark){.p{fill:#141a21}.i{fill:#8db8ec}}</style>'
    '<rect class="p" width="32" height="32" rx="6"/>'
    '<circle class="i" cx="16" cy="16" r="9"/>'
    '<circle class="p" cx="16" cy="16" r="4"/></svg>'
)
FAVICON_URI = "data:image/svg+xml;base64," + base64.b64encode(FAVICON_SVG.encode()).decode()


def sayfa(baslik, govde, kok="", aciklama="DipWatch: uluslararası siyaset olay takibi", secili=None, tur="website"):
    """secili: menüde işaretlenecek bölge anahtarı ('' = Tümü, None = hiçbiri). tur: og:type."""
    e = escape

    def menu_linki(href, ad, anahtar):
        isaret = ' aria-current="page"' if anahtar == secili else ""
        sinif = f' class="b-{anahtar}"' if anahtar else ""
        return f'<a href="{href}"{sinif}{isaret}>{e(ad)}</a>'

    menu = menu_linki(f"{kok}index.html", "Tümü", "") + "".join(
        menu_linki(f"{kok}bolge/{b}.html", ad, b) for b, ad in BOLGE_ADLARI.items())
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(baslik)}</title>
<meta name="description" content="{e(aciklama)}">
<meta property="og:type" content="{tur}">
<meta property="og:locale" content="tr_TR">
<meta property="og:site_name" content="DipWatch">
<meta property="og:title" content="{e(baslik)}">
<meta property="og:description" content="{e(aciklama)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{e(baslik)}">
<meta name="twitter:description" content="{e(aciklama)}">
<meta name="theme-color" content="#f1f3f2" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#141a21" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{FAVICON_URI}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTLAR}">
<link rel="stylesheet" href="{kok}stil.css">
</head>
<body>
<a class="atla" href="#icerik">İçeriğe geç</a>
<header class="masa">
  <div class="masa-ic">
    <a class="logo" href="{kok}index.html">DipWatch</a>
    <span class="masa-alt">Uluslararası olay masası</span>
  </div>
  <nav class="bolgeler" aria-label="Bölgeler">{menu}</nav>
</header>
<main id="icerik">
{govde}
</main>
<footer>Başlıklar ve linkler kaynakların kendisine aittir. DipWatch haberleri otomatik toplar ve gruplar.
Özetler hata içerebilir; bir bilgiyi kullanmadan önce kaynağına bakın.</footer>
<script src="{kok}filtre.js"></script>
</body>
</html>
"""


def _baslik_dili(o):
    """o['baslik'] hangi kaynağın başlığıysa onun dili; bulunamazsa ilk kaynağın dili.
    LLM özeti ya da makine çevirisi varsa başlık Türkçedir."""
    if o.get("turkce_ozet_var") or o.get("makine_cevirisi"):
        return "tr"
    kaynaklar = o.get("kaynaklar") or ()
    for k in kaynaklar:
        if k.get("baslik") == o["baslik"]:
            return k.get("dil") or ""
    return kaynaklar[0].get("dil", "") if kaynaklar else ""


def _yeni_mi(son_haber_iso, olusturulma_iso):
    """Son haber, site üretiminden en fazla 1 saat önce gelmişse "yeni" sayılır."""
    son, uretim = zaman(son_haber_iso), zaman(olusturulma_iso)
    return bool(son and uretim and timedelta(0) <= (uretim - son) <= timedelta(hours=1))


def _kaynak_ozeti_satiri(o):
    """Özet yoksa liste satırı bilgisiz kalmasın diye: ilk 3 kaynak adı, dil karışımı, ülkeler."""
    e = escape
    adlar, gorulen = [], set()
    for k in o.get("kaynaklar") or ():
        ad = k.get("kaynak")
        if ad and ad not in gorulen:
            gorulen.add(ad)
            adlar.append(ad)
        if len(adlar) >= 3:
            break
    diller = []
    for k in o.get("kaynaklar") or ():
        d = DILLER.get(k.get("dil"), (k.get("dil") or "").upper())
        if d and d not in diller:
            diller.append(d)
    parcalar = []
    if adlar:
        parcalar.append(", ".join(adlar))
    if len(diller) > 1:
        parcalar.append("/".join(diller[:3]))
    ulkeler = [u for u in (o.get("ulkeler") or ()) if u][:3]
    if ulkeler:
        parcalar.append(", ".join(ulkeler))
    if not parcalar:
        return ""
    return f'<p class="kaynak-ozeti">{" · ".join(e(p) for p in parcalar)}</p>'


def olay_satiri(o, kok, olusturulma, manset=False):
    e = escape
    son = zaman(o["son_haber"])
    b = e(o["bolge"])
    onem = f'<span class="onem">önem {o["onem"]}/5</span>' if o.get("onem") else ""
    ozet = f'<p class="ozet">{e(o["ozet"])}</p>' if o.get("ozet") else ""
    kaynak_ozeti = "" if o.get("ozet") else _kaynak_ozeti_satiri(o)
    bd = _baslik_dili(o)
    dil_rozeti = (f'<span class="dil" title="Başlığın dili">{e(DILLER.get(bd, bd.upper()))}</span>'
                  if bd and bd != "tr" else "")
    yeni = '<span class="yeni-etiket">Yeni</span>' if _yeni_mi(o["son_haber"], olusturulma) else ""
    sinif = f"olay b-{b}" + (" olay-manset" if manset else "")
    sayi = o["kaynak_sayisi"]
    yayilim_genislik = min(100, round(sayi / 20 * 100))
    return (f'<li class="{sinif}" data-ara="{e(arama_metni(o))}">'
            f'<div class="olay-govde">'
            f'<a class="baslik" href="{kok}olay/{o["id"]}.html">{e(o["baslik"])}</a>{dil_rozeti}{yeni}{ozet}{kaynak_ozeti}'
            f'<div class="meta"><a class="bolge-adi" href="{kok}bolge/{b}.html">{e(bolge_adi(o["bolge"]))}</a>'
            f'<time class="zaman" datetime="{e(o["son_haber"])}">son haber '
            f'<span class="zaman-deger">{saat_dk(son)}</span></time>{onem}</div>'
            f'</div>'
            f'<div class="yayilim" title="{sayi} farklı yayın kuruluşu">'
            f'<span class="sayi">{sayi}</span><span class="birim">kaynak</span>'
            f'<span class="yayilim-cubuk" style="--g:{yayilim_genislik}%" aria-hidden="true"></span>'
            f'</div></li>')


def arama_metni(o):
    # Her kaynağın tam başlığını basmak (bazı olaylarda 70'in üzerinde kaynak var) index.html'i
    # 2 MB'a çıkaran asıl kalemdi; kazanç arama kalitesine oranla çok düşüktü (genelde aynı haberin
    # küçük farklı ifadeleri). Kaynak ADLARI (kısa) kalır, tam başlıkları yalnızca olay sayfasında var.
    adlar, gorulen = [], set()
    for k in o["kaynaklar"]:
        ad = k["kaynak"]
        if ad not in gorulen:
            gorulen.add(ad)
            adlar.append(ad)
    parcalar = [o["baslik"], o.get("ozet") or "", " ".join(o.get("ulkeler") or []),
                " ".join(o.get("etiketler") or []), " ".join(adlar)]
    # filtre.js ile aynı sadeleştirme: büyük/küçük harf ve ı/i farkı aramayı bozmasın
    return " ".join(parcalar).lower().replace("̇", "").replace("ı", "i")


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


def bolge_seridi(olaylar, kok):
    """Ana sayfanın imza öğesi: birden fazla kaynaklı olayların bölgelere dağılımı, tıklanabilir şerit."""
    sayac = defaultdict(int)
    for o in olaylar:
        if o["kaynak_sayisi"] >= 2:
            sayac[o["bolge"]] += 1
    toplam = sum(sayac.values())
    if not toplam:
        return ""
    sirali = sorted(sayac.items(), key=lambda x: -x[1])
    parcalar = "".join(
        f'<a class="serit-parca b-{escape(b)}" href="{kok}bolge/{escape(b)}.html" style="flex-grow:{n}"'
        f' title="{escape(bolge_adi(b))}: {n} olay" aria-label="{escape(bolge_adi(b))}: {n} olay"><span class="serit-ad">{escape(bolge_adi_kisa(b))}</span>'
        f'<span class="serit-sayi">{n}</span></a>'
        for b, n in sirali)
    return (f'<section class="serit" aria-labelledby="serit-baslik">'
            f'<h2 id="serit-baslik">Son 72 saatte birden fazla kaynağın haber yaptığı {toplam} olay</h2>'
            f'<div class="serit-cubuk">{parcalar}</div></section>')


def liste_sayfasi(baslik, olaylar_tum, kok, olusturulma, secili, serit=False, arsiv=False):
    """arsiv=False: yalnızca birden fazla kaynaklı olaylar (ana/bölge sayfaları).
    arsiv=True: yalnızca tek kaynaklı olaylar (performans için ana listeden çıkarılan arşiv sayfası).
    `olaylar_tum` her iki modda da filtrelenmemiş tam liste olarak verilir; bölge şeridi ve
    "tek kaynaklı N olay" bağlantısı doğru sayabilsin diye ayrım burada yapılır."""
    e = escape
    if arsiv:
        olaylar = [o for o in olaylar_tum if o["kaynak_sayisi"] < 2]
    else:
        olaylar = [o for o in olaylar_tum if o["kaynak_sayisi"] >= 2]
    tek_sayi = sum(1 for o in olaylar_tum if o["kaynak_sayisi"] < 2)

    gunler = gunlere_bol(olaylar)
    atla = "".join(
        f'<a href="#g{g.isoformat()}">{g.day} {AYLAR[g.month - 1]} <span class="gun-sayi">{len(liste)}</span></a>'
        for g, liste in gunler)
    bolumler = []
    for g, liste in gunler:
        # Her günün en çok kaynaklı 1-3 olayı "manşet" gibi büyütülür (liste zaten önem/kaynak
        # sayısına göre sıralı geldiği için en baştaki 1-3 tanesi budur).
        manset_hakki = 3
        satirlar = []
        for o in liste:
            manset = (not arsiv) and o["kaynak_sayisi"] >= 2 and manset_hakki > 0
            if manset:
                manset_hakki -= 1
            satirlar.append(olay_satiri(o, kok, olusturulma, manset=manset))
        bolumler.append(f'<section class="gun" id="g{g.isoformat()}"><h2>{gun_adi(g)}</h2>'
                        f'<ol class="olaylar">{"".join(satirlar)}</ol></section>')

    if arsiv:
        bos = '<p class="bos">Bu kapsamda tek kaynaklı olay yok.</p>' if not olaylar else ""
        geri = liste_href(kok, secili)
        arac_link = (f'<a class="arsiv-donus" href="{geri}">'
                     f'← {"Bölgenin tüm olaylarına" if secili else "Tüm olaylara"} dön</a>')
    else:
        bos = ('<p class="bos">Bu bölgede son 72 saatte birden fazla kaynaklı olay yok. '
               'Diğer bölgelere üstteki menüden bakabilirsin.</p>' if not olaylar else "")
        arac_link = (f'<a class="arsiv-link" href="{arsiv_href(kok, secili)}">{tek_sayi} tek kaynaklı olayı gör →</a>'
                     if tek_sayi else "")

    bolge_sinifi = f" b-{e(secili)}" if secili else ""
    govde = f"""<div class="sayfa-bas{bolge_sinifi}">
  <h1>{e(baslik)}</h1>
  <p class="alt">{len(olaylar)} olay, son güncelleme {tarih_saat(zaman(olusturulma))} (İstanbul saati)</p>
</div>
{bolge_seridi(olaylar_tum, kok) if serit else ""}
<div class="araclar">
  <label class="ara-kutu"><span class="gizli">Ara</span>
    <input type="search" id="ara" placeholder="Başlık, ülke veya kaynakta ara ( / ile odaklan )"></label>
  {arac_link}
  <nav class="gunler" aria-label="Günler">{atla}</nav>
</div>
<p id="sonuc-sayisi" class="gizli" role="status" aria-atomic="true"></p>
{bos}{"".join(bolumler)}
<p class="bos" id="sonuc-yok" hidden>Aramana uyan olay yok. Başka bir kelime dene.</p>"""
    return sayfa(f"{baslik} | DipWatch", govde, kok, secili=secili)


def _cizelge_gruplari(kaynaklar):
    """Yayın saatine göre sıralı kaynaklar: aynı günde ardışık gelen aynı-kaynaklı haberler
    (bir yayın kuruluşunun olayı birkaç kez güncellemesi) tek grupta toplanır."""
    gruplar = []
    for k in kaynaklar:
        d = zaman(k.get("yayin"))
        gun = d.date() if d else None
        if gruplar and gruplar[-1]["gun"] == gun and gruplar[-1]["kaynak"] == k.get("kaynak"):
            gruplar[-1]["ogeler"].append(k)
        else:
            gruplar.append({"gun": gun, "kaynak": k.get("kaynak"), "ogeler": [k]})
    return gruplar


def _cizelge_grup_html(g):
    e = escape
    ogeler = g["ogeler"]
    ilk = ogeler[0]
    dil = ilk.get("dil") or ""
    dil_rozeti = e(DILLER.get(dil, dil.upper()))
    if len(ogeler) == 1:
        tur = TUR_ETIKETLERI.get(ilk.get("tur"))
        tur_html = f'<span class="dil" title="İçerik türü">{e(tur)}</span>' if tur else ""
        return (f'<li data-dil="{e(dil)}"><time>{saat_dk(zaman(ilk.get("yayin")))}</time>'
                f'<div><span class="kaynak">{e(ilk["kaynak"])}</span>'
                f'<span class="dil" title="Haberin dili">{dil_rozeti}</span>{tur_html}'
                f'<a href="{e(guvenli_link(ilk["link"]))}" rel="noopener noreferrer" target="_blank">{e(ilk["baslik"])}</a>'
                f'</div></li>')
    ic = "".join(
        f'<li><time>{saat_dk(zaman(k.get("yayin")))}</time>'
        f'<a href="{e(guvenli_link(k["link"]))}" rel="noopener noreferrer" target="_blank">{e(k["baslik"])}</a></li>'
        for k in ogeler)
    return (f'<li class="cizelge-grup" data-dil="{e(dil)}"><time>{saat_dk(zaman(ilk.get("yayin")))}</time>'
            f'<div><span class="kaynak">{e(g["kaynak"] or "")}</span>'
            f'<span class="dil" title="Haberin dili">{dil_rozeti}</span>'
            f'<span class="grup-sayi">{len(ogeler)} güncelleme</span>'
            f'<ol class="cizelge-ic">{ic}</ol></div></li>')


def olay_sayfasi(o, kok="../"):
    e = escape
    b = e(o["bolge"])
    ilk, son = zaman(o["ilk_haber"]), zaman(o["son_haber"])
    kaynaklar = sorted(o["kaynaklar"], key=lambda k: k.get("yayin") or "")

    if o.get("makine_cevirisi"):
        ozet = ((f'<p class="ozet buyuk">{e(o["ozet"])}</p>' if o.get("ozet") else "")
                + '<p class="not">Bu başlık ve metin, kaynak haberlerden birinin makine çevirisidir; '
                  'olayın özeti henüz yazılmadı.</p>')
    elif o.get("ozet"):
        ozet = f'<p class="ozet buyuk">{e(o["ozet"])}</p>'
    else:
        ozet = ('<p class="not">Bu olay için henüz Türkçe özet yok. Başlık kaynaklardan birinden alındı; '
                'ayrıntı için aşağıdaki haberlere bak.</p>')

    etiketler = "".join(f'<li>{e(x)}</li>' for x in (o.get("ulkeler") or []) + (o.get("etiketler") or []))
    etiketler = f'<ul class="etiketler" aria-label="Ülkeler ve etiketler">{etiketler}</ul>' if etiketler else ""

    # Zaman çizelgesi: ardışık aynı-kaynaklı haberler gruplanır (bkz. _cizelge_gruplari); varsayılan
    # olarak ilk LIMIT haber doğrudan görünür, kalanı <details> içinde "Tüm N haberi göster" ile daralır.
    LIMIT = 8
    gruplar = _cizelge_gruplari(kaynaklar)
    ilk_cizelge, devam_cizelge = [], []
    gosterilen, onceki_gun = 0, None
    for g in gruplar:
        parca = []
        if g["gun"] and g["gun"] != onceki_gun:
            parca.append(f'<li class="cizelge-gun">{gun_adi(g["gun"])}</li>')
            onceki_gun = g["gun"]
        parca.append(_cizelge_grup_html(g))
        (ilk_cizelge if gosterilen < LIMIT else devam_cizelge).extend(parca)
        gosterilen += len(g["ogeler"])

    cizelge_html = "".join(ilk_cizelge)
    if devam_cizelge:
        cizelge_html += (f'<li class="cizelge-devam"><details><summary>Tüm {len(kaynaklar)} haberi göster</summary>'
                         f'<ol class="cizelge cizelge-ic-govde">{"".join(devam_cizelge)}</ol></details></li>')

    diller_mevcut = [d for d in ("tr", "en") if any((k.get("dil") or "") == d for k in kaynaklar)]
    dil_filtre = ""
    if len({k.get("dil") or "" for k in kaynaklar}) > 1 and diller_mevcut:
        dugmeler = ['<button type="button" data-dil="" aria-pressed="true">Tümü</button>'] + [
            f'<button type="button" data-dil="{d}" aria-pressed="false">{e(DILLER.get(d, d.upper()))}</button>'
            for d in diller_mevcut]
        dil_filtre = (f'<div class="dil-filtre" role="group" aria-label="Habere göre dil filtresi">'
                     f'{"".join(dugmeler)}</div>')

    yayinlar = defaultdict(list)
    for k in kaynaklar:
        yayinlar[k["kaynak"]].append(k)
    kaynak_listesi = "".join(
        f'<li><h3>{e(ad)}</h3><ul>'
        + "".join(f'<li><a href="{e(guvenli_link(k["link"]))}" rel="noopener noreferrer" target="_blank">'
                  f'{e(k["baslik"])}</a></li>' for k in liste)
        + "</ul></li>"
        for ad, liste in sorted(yayinlar.items(), key=lambda x: x[0].lower()))

    onem = f'<div><dt>Önem</dt><dd>{o["onem"]}/5</dd></div>' if o.get("onem") else ""
    govde = f"""<article class="olay-sayfa b-{b}">
  <a class="bolge-adi" href="{kok}bolge/{b}.html">{e(bolge_adi(o["bolge"]))}</a>
  <h1>{e(o["baslik"])}</h1>
  <dl class="olgular">
    <div><dt>Kaynak</dt><dd>{o["kaynak_sayisi"]}</dd></div>
    <div><dt>Haber</dt><dd>{len(kaynaklar)}</dd></div>
    <div><dt>İlk haber</dt><dd>{tarih_saat(ilk)}</dd></div>
    <div><dt>Son haber</dt><dd>{tarih_saat(son)}</dd></div>{onem}
  </dl>
  {ozet}
  {etiketler}
  <h2>Zaman çizelgesi</h2>
  <p class="aciklama">Haberler yayın saatine göre sıralı (İstanbul saati). Başlığa tıklayınca haber kaynağında açılır.</p>
  {dil_filtre}
  <ol class="cizelge">{cizelge_html}</ol>
  <h2>Yayın kuruluşlarına göre kaynaklar</h2>
  <ul class="kaynaklar">{kaynak_listesi}</ul>
</article>"""
    return sayfa(f"{o['baslik']} | DipWatch", govde, kok, aciklama=(o.get("ozet") or o["baslik"])[:200], tur="article")


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
        liste_sayfasi("Son olaylar", olaylar, "", olusturulma, secili="", serit=True), encoding="utf-8")
    # Tek kaynaklı olaylar (çoğunluk) performans için ana listeden çıkarılır, ayrı bir arşiv
    # sayfasında toplanır; ana sayfadaki/bölgedeki araç çubuğu buraya link verir.
    (cikti / "tek-kaynakli.html").write_text(
        liste_sayfasi("Tek kaynaklı olaylar", olaylar, "", olusturulma, secili="", arsiv=True), encoding="utf-8")
    bolgeye_gore = defaultdict(list)
    for o in olaylar:
        bolgeye_gore[o["bolge"]].append(o)
    for b in set(BOLGE_ADLARI) | set(bolgeye_gore):
        liste = bolgeye_gore.get(b, [])
        (cikti / "bolge" / f"{b}.html").write_text(
            liste_sayfasi(bolge_adi(b), liste, "../", olusturulma, secili=b), encoding="utf-8")
        (cikti / "bolge" / f"{b}-tek.html").write_text(
            liste_sayfasi(f"{bolge_adi(b)} — tek kaynaklı olaylar", liste, "../", olusturulma, secili=b, arsiv=True),
            encoding="utf-8")
    for o in olaylar:
        (cikti / "olay" / f"{o['id']}.html").write_text(olay_sayfasi(o), encoding="utf-8")

    log.info("site oluşturuldu: %s · %d olay · %d bölge", cikti, len(olaylar), len(bolgeye_gore))
    return len(olaylar)
