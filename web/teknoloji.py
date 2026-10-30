"""data/teknoloji.json -> teknoloji.html: teknoloji ve siber güvenlik haberleri (bkz. teknoloji/ modülü).

Haberler en yeni en üstte, İstanbul saatine göre günlere bölünmüş listelenir. Kategori düğmeleri,
kaynak seçimi ve arama kutusu filtre.js ile çalışır; seçim adres çubuğuna da yazılır
(teknoloji.html?kategori=siber_guvenlik&kaynak=CISA), böylece filtrelenmiş görünüm paylaşılabilir.
JavaScript kapalıysa filtreler gizlenir, tüm haberler görünür.
"""
import json
import logging
import shutil
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

from .build import STATIK, gun_adi, guvenli_link, saat_dk, sayfa, tarih_saat, zaman

log = logging.getLogger("dipwatch.web")
KATEGORILER = {"siber_guvenlik": "Siber güvenlik", "teknoloji": "Teknoloji"}
BASLIK = "Teknoloji ve siber güvenlik"


def _arama_metni(h):
    parcalar = [h["baslik"], h.get("ozet") or "", h["kaynak"]] + [d["kaynak"] for d in h.get("diger_kaynaklar") or ()]
    return " ".join(parcalar).lower().replace("̇", "").replace("ı", "i")


def haber_satiri(h):
    e = escape
    kat = h.get("kategori") or "teknoloji"
    ozet = f'<p class="ozet">{e(h["ozet"])}</p>' if h.get("ozet") else ""
    digerleri = h.get("diger_kaynaklar") or []
    ayrica = ""
    if digerleri:
        linkler = ", ".join(
            f'<a href="{e(guvenli_link(d["link"]))}" rel="noopener noreferrer" target="_blank" '
            f'title="{e(d.get("baslik") or "")}">{e(d["kaynak"])}</a>' for d in digerleri)
        ayrica = f'<p class="ayrica">Ayrıca: {linkler}</p>'
    return (f'<li class="tekno-haber k-{e(kat)}" data-kategori="{e(kat)}" data-kaynak="{e(h["kaynak"])}" '
            f'data-ara="{e(_arama_metni(h))}">'
            f'<a class="baslik" href="{e(guvenli_link(h["link"]))}" rel="noopener noreferrer" target="_blank">'
            f'{e(h["baslik"])}</a>{ozet}'
            f'<div class="meta"><span class="kategori-rozet">{e(KATEGORILER.get(kat, kat))}</span>'
            f'<span class="kaynak-adi">{e(h["kaynak"])}</span>'
            f'<time class="zaman" datetime="{e(h["yayin"])}"><span class="zaman-deger">{saat_dk(zaman(h["yayin"]))}</span></time>'
            f'</div>{ayrica}</li>')


def teknoloji_sayfasi(veri, kok=""):
    e = escape
    haberler = sorted(veri.get("haberler") or [], key=lambda h: h["yayin"], reverse=True)
    gunler = defaultdict(list)
    for h in haberler:
        d = zaman(h["yayin"])
        if d:
            gunler[d.date()].append(h)
    bolumler = "".join(
        f'<section class="gun" id="g{g.isoformat()}"><h2>{gun_adi(g)}</h2>'
        f'<ol class="tekno-liste">{"".join(haber_satiri(h) for h in liste)}</ol></section>'
        for g, liste in sorted(gunler.items(), reverse=True))

    kat_sayi = Counter(h.get("kategori") for h in haberler)
    kat_dugmeleri = [f'<button type="button" data-kategori="" aria-pressed="true">Tümü <span class="gun-sayi">{len(haberler)}</span></button>'] + [
        f'<button type="button" data-kategori="{k}" aria-pressed="false">{e(ad)} <span class="gun-sayi">{kat_sayi.get(k, 0)}</span></button>'
        for k, ad in KATEGORILER.items()]
    kaynak_sayi = Counter(h["kaynak"] for h in haberler)
    kaynak_adlari = list(dict.fromkeys(list(veri.get("kaynaklar") or []) + sorted(kaynak_sayi)))
    secenekler = '<option value="">Tüm kaynaklar</option>' + "".join(
        f'<option value="{e(k)}">{e(k)} ({kaynak_sayi.get(k, 0)})</option>' for k in kaynak_adlari)

    bos = ('<p class="bos">Henüz teknoloji haberi toplanmadı. <code>python -m teknoloji tur</code> çalıştırınca burada görünür.</p>'
           if not haberler else "")
    govde = f"""<div class="sayfa-bas b-tekno">
  <h1>{BASLIK}</h1>
  <p class="alt">Son {veri.get("gun", 7)} günde {len(haberler)} haber, son güncelleme {tarih_saat(zaman(veri.get("olusturulma")))} (İstanbul saati).
  Aynı haberi birden fazla kaynak verdiyse bir kez listelenir, diğerleri "Ayrıca" satırında.</p>
</div>
<div class="araclar tekno-araclar" hidden>
  <label class="ara-kutu"><span class="gizli">Ara</span>
    <input type="search" id="tekno-ara" placeholder="Başlık, özet veya kaynakta ara ( / ile odaklan )"></label>
  <div class="tekno-kategori" role="group" aria-label="Kategoriye göre filtre">{"".join(kat_dugmeleri)}</div>
  <label class="kaynak-sec"><span>Kaynak</span> <select id="tekno-kaynak">{secenekler}</select></label>
</div>
<p id="sonuc-sayisi" class="gizli" role="status" aria-atomic="true"></p>
{bos}{bolumler}
<p class="bos" id="sonuc-yok" hidden>Seçtiğin filtrelere uyan haber yok.</p>"""
    return sayfa(f"{BASLIK} | DipWatch", govde, kok, secili="teknoloji",
                 aciklama="DipWatch: dünya genelinden teknoloji ve siber güvenlik haberleri")


def yaz(girdi: Path, cikti: Path) -> int:
    """teknoloji.json'dan cikti/teknoloji.html üretir. Dosya yoksa boş bir sayfa yazılır (menüdeki link kırılmasın)."""
    veri = json.loads(girdi.read_text(encoding="utf-8")) if girdi.exists() else {}
    cikti.mkdir(parents=True, exist_ok=True)
    for dosya in STATIK.iterdir():  # yalnızca teknoloji sayfası üretilirken de stil/JS güncel olsun
        shutil.copy(dosya, cikti / dosya.name)
    (cikti / "teknoloji.html").write_text(teknoloji_sayfasi(veri), encoding="utf-8")
    n = len(veri.get("haberler") or [])
    log.info("teknoloji sayfası oluşturuldu: %s · %d haber", cikti / "teknoloji.html", n)
    return n
