"""RSS'i olmayan (ya da RSS'i çalışmayan) kaynaklar için basit sayfa kazıyıcı.

Bir liste sayfasındaki <a> etiketlerinden, kaynağa özel `link_deseni` regex'ine uyanlar haber sayılır;
linkin metni başlık olur. Yayın tarihi, linke en yakın <time datetime="..."> öğesinden alınır (önce
linkten sonra, bir sonraki habere kadar; yoksa linkten önce). Tarih bulunamazsa çekilme anı kullanılır.
Yalnızca standart kütüphane kullanır; sayfa başına tek istek atar.
"""
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

from collector.fetch import _indir, temizle

MIN_KELIME = 3


class _Ayristirici(HTMLParser):
    def __init__(self, taban: str, desen: re.Pattern):
        super().__init__(convert_charrefs=True)
        self.taban, self.desen = taban, desen
        self.olaylar = []  # ("a", {link, baslik}) ve ("t", iso) sırayla
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            link = urljoin(self.taban, a["href"])
            if self.desen.search(link):
                self._a = {"link": link, "parcalar": []}
        elif tag == "time" and a.get("datetime"):
            self.olaylar.append(("t", a["datetime"]))

    def handle_data(self, data):
        if self._a is not None:
            self._a["parcalar"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            baslik = temizle(" ".join(self._a["parcalar"]), 300)
            self.olaylar.append(("a", {"link": self._a["link"], "baslik": baslik}))
            self._a = None


def _iso(metin: str | None) -> str | None:
    if not metin:
        return None
    try:
        d = datetime.fromisoformat(metin.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def ayristir(html_metni: str, taban: str, link_deseni: str) -> list[dict]:
    """HTML -> [{link, baslik, yayin(None olabilir)}]; aynı link bir kez, kısa (menü vb.) metinler atlanır."""
    p = _Ayristirici(taban, re.compile(link_deseni))
    p.feed(html_metni)
    olaylar = p.olaylar
    sonuc, gorulen = [], set()
    for i, (tur, deger) in enumerate(olaylar):
        if tur != "a":
            continue
        tarih = None
        for t, d in olaylar[i + 1:]:  # linkten sonra, bir sonraki linke kadar
            if t == "a":
                break
            tarih = d
            break
        if tarih is None:
            for t, d in reversed(olaylar[:i]):  # yoksa linkten önce, bir önceki linke kadar
                if t == "a":
                    break
                tarih = d
                break
        if deger["link"] in gorulen or len(deger["baslik"].split()) < MIN_KELIME:
            continue
        gorulen.add(deger["link"])
        sonuc.append({**deger, "yayin": _iso(tarih)})
    return sonuc


def kazi(url: str, link_deseni: str, zaman_asimi: int = 20) -> list[dict]:
    ham = _indir(url, zaman_asimi)
    return ayristir(ham.decode("utf-8", errors="replace"), url, link_deseni)
