"""Ayarlar ve kaynak listesinin okunması."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KOK = Path(__file__).resolve().parent.parent
# Google News "site:" sorgusu. Türkçe kaynaklar Türkiye baskısında aranmalı; İngilizce baskı onları
# neredeyse hiç döndürmüyor. Seyrek yayın yapan kaynaklar (düşünce kuruluşları) için gn_sure: 7d.
GOOGLE_NEWS = "https://news.google.com/rss/search?q=site:{alan}+when:{sure}&{baski}"
GN_BASKI = {"tr": "hl=tr&gl=TR&ceid=TR:tr", "en": "hl=en-US&gl=US&ceid=US:en"}


def google_news_url(alan_adi: str, dil: str = "en", sure: str = "1d") -> str:
    return GOOGLE_NEWS.format(alan=alan_adi, sure=sure, baski=GN_BASKI.get(dil, GN_BASKI["en"]))


@dataclass
class Kaynak:
    ad: str
    bolge: str
    url: str
    tur: str = ""
    dil: str = "en"
    ulke: str = ""
    yontem: str = "rss"


@dataclass
class Ayarlar:
    kaynak_dosyasi: Path = KOK / "sources.yaml"
    veritabani: Path = KOK / "data" / "dipwatch.db"
    cikti_klasoru: Path = KOK / "data"
    # Gruplama
    benzerlik_esigi: float = 0.28      # TF-IDF kosinüs; üstündeyse aynı olay
    olay_penceresi_saat: int = 36      # bir olaya bu kadar saat yeni haber gelmezse kapanır
    idf_penceresi_saat: int = 72
    # Özet (Claude)
    model: str = os.environ.get("DIPWATCH_MODEL", "claude-opus-5-5")
    efor: str = os.environ.get("DIPWATCH_EFOR", "low")
    ozet_min_kaynak: int = int(os.environ.get("DIPWATCH_OZET_MIN_KAYNAK", "2"))
    ozet_max_olay_tur: int = 40        # bir turda en fazla kaç olay özetlensin
    llm_birlestirme: bool = True       # farklı dillerdeki aynı olayı Claude ile birleştir
    # Çekme
    zaman_asimi: int = 20
    paralel: int = 16
    export_saat: int = 72
    extra: dict = field(default_factory=dict)


def kaynaklari_yukle(yol: Path, kapalilar: bool = False) -> list[Kaynak]:
    veri = yaml.safe_load(open(yol, encoding="utf-8"))["bolgeler"]
    sonuc = []
    for bolge, liste in veri.items():
        for s in liste or []:
            if s.get("durum") == "kapali" and not kapalilar:
                continue
            url = s.get("url") or google_news_url(s["alan_adi"], s.get("dil", "en"), s.get("gn_sure", "1d"))
            sonuc.append(Kaynak(ad=s["ad"], bolge=bolge, url=url, tur=s.get("tur", ""),
                                dil=s.get("dil", "en"), ulke=s.get("ulke", ""),
                                yontem=s.get("yontem", "rss")))
    return sonuc
