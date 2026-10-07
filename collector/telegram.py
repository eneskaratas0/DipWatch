"""Telegram bildirimleri (4. adım): seçilen bölge / anahtar kelimelerde yeni veya büyüyen olay olunca mesaj.

Bot anahtarı ve sohbet kimliği .env dosyasından okunur (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).
Hangi olayların bildirileceği proje kökündeki bildirim.yaml dosyasında ayarlanır.
"""
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import cluster, export
from .config import KOK

log = logging.getLogger("dipwatch.telegram")
API = "https://api.telegram.org/bot{token}/{metod}"

SEMA = """
CREATE TABLE IF NOT EXISTS bildirim (
    olay_id INTEGER PRIMARY KEY,
    kaynak_sayisi INTEGER,     -- son bildirimde kaç kaynak vardı
    mesaj_id INTEGER,          -- ilk mesajın Telegram kimliği; güncellemeler buna yanıt olarak gider
    zaman TEXT
);
CREATE TABLE IF NOT EXISTS bildirim_durum (ad TEXT PRIMARY KEY, deger TEXT);
"""

BOLGE_ADLARI = {
    "orta_dogu": "Orta Doğu", "rusya_ukrayna_kafkasya": "Rusya, Ukrayna, Kafkasya", "avrupa": "Avrupa",
    "asya_pasifik": "Asya-Pasifik", "afrika": "Afrika", "amerika": "Amerika", "turkiye": "Türkiye",
    "kuresel": "Küresel",
}


@dataclass
class Kurallar:
    bolgeler: list = field(default_factory=list)
    anahtar_kelimeler: list = field(default_factory=list)
    min_kaynak: int = 2
    min_onem: int = 0
    buyume_esigi: int = 3
    tur_basina_en_fazla: int = 10
    gosterilecek_kaynak: int = 6
    site_adresi: str = ""

    @classmethod
    def yukle(cls, yol: Path = KOK / "bildirim.yaml") -> "Kurallar":
        veri = (yaml.safe_load(yol.read_text(encoding="utf-8")) if yol.exists() else None) or {}
        bilinen = {k: v for k, v in veri.items() if k in cls.__dataclass_fields__ and v is not None}
        k = cls(**bilinen)
        k.bolgeler = [str(b) for b in k.bolgeler or []]
        k.anahtar_kelimeler = [str(a) for a in k.anahtar_kelimeler or []]
        return k


_HARFLER = str.maketrans("İIıŞşĞğÇçÖöÜüÂâÎîÛû", "iiissggccoouuaaiiuu")


def sadelestir(metin: str) -> str:
    """Büyük/küçük harf ve Türkçe harf farklarını siler: 'İRAN', 'Iran', 'iran' hepsi 'iran' olur."""
    return (metin or "").translate(_HARFLER).lower()


def eslesen_kelimeler(olay: dict, kelimeler: list) -> list:
    metin = sadelestir(" ".join([olay["baslik"] or "", olay["ozet"] or "", *olay["ulkeler"], *olay["etiketler"],
                                *(k["baslik"] or "" for k in olay["kaynaklar"])]))
    return [k for k in kelimeler if re.search(r"(?<!\w)" + re.escape(sadelestir(k)), metin)]


def uyuyor_mu(olay: dict, kurallar: Kurallar) -> bool:
    if olay["kaynak_sayisi"] < kurallar.min_kaynak:
        return False
    if kurallar.min_onem and (olay["onem"] or 0) < kurallar.min_onem:
        return False
    if not kurallar.bolgeler and not kurallar.anahtar_kelimeler:
        return True
    return olay["bolge"] in kurallar.bolgeler or bool(eslesen_kelimeler(olay, kurallar.anahtar_kelimeler))


def _saat(iso: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(iso).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m %H:%M")
    except Exception:
        return iso[:16].replace("T", " ")


def _kisalt(metin, n):
    metin = metin or ""
    return metin if len(metin) <= n else metin[:n - 1].rstrip() + "…"


def mesaj_metni(olay: dict, kurallar: Kurallar, onceki_kaynak: int | None = None) -> str:
    e = html.escape
    if onceki_kaynak is None:
        ust = "🆕 <b>Yeni olay</b>"
    else:
        ust = f"📈 <b>Olay büyüyor</b> ({onceki_kaynak} → {olay['kaynak_sayisi']} kaynak)"
    bolge = BOLGE_ADLARI.get(olay["bolge"], olay["bolge"])
    bilgi = [bolge, f"{olay['kaynak_sayisi']} kaynak", f"son haber {_saat(olay['son_haber'])}"]
    if olay["onem"]:
        bilgi.append("★" * olay["onem"])
    satirlar = [ust, "", f"<b>{e(_kisalt(olay['baslik'], 300))}</b>", f"<i>{e(' · '.join(bilgi))}</i>"]
    if olay["ozet"]:
        satirlar += ["", e(_kisalt(olay["ozet"], 1500))]
    kelimeler = eslesen_kelimeler(olay, kurallar.anahtar_kelimeler)
    if kelimeler:
        satirlar.append(f"🔎 {e(', '.join(kelimeler))}")

    # Her yayın kuruluşundan en yeni haber; en yeniler önce
    gorulen, kaynaklar = set(), []
    for k in sorted(olay["kaynaklar"], key=lambda k: k["yayin"] or "", reverse=True):
        if k["kaynak"] in gorulen or not re.match(r"https?://", k["link"] or ""):
            continue
        gorulen.add(k["kaynak"])
        kaynaklar.append(k)
    satirlar += ["", "<b>Kaynaklar</b>"]
    for k in kaynaklar[:kurallar.gosterilecek_kaynak]:
        satirlar.append(f'• <a href="{e(k["link"])}">{e(k["kaynak"])}</a>: {e(k["baslik"] or "")}')
    if len(kaynaklar) > kurallar.gosterilecek_kaynak:
        satirlar.append(f"… ve {len(kaynaklar) - kurallar.gosterilecek_kaynak} kaynak daha")
    if kurallar.site_adresi:
        adres = kurallar.site_adresi.rstrip("/") + f"/olay/{olay['id']}.html"
        satirlar += ["", f'<a href="{e(adres)}">Olayın tüm kaynakları ve zaman çizelgesi</a>']

    return "\n".join(satirlar)


class Bot:
    def __init__(self, token: str, chat_id: str, zaman_asimi: int = 20):
        self.token, self.chat_id, self.zaman_asimi = token, chat_id, zaman_asimi

    def cagir(self, metod: str, **parametre):
        istek = urllib.request.Request(
            API.format(token=self.token, metod=metod), data=json.dumps(parametre).encode(),
            headers={"Content-Type": "application/json"})
        for deneme in range(3):
            try:
                with urllib.request.urlopen(istek, timeout=self.zaman_asimi) as yanit:
                    return json.load(yanit)["result"]
            except urllib.error.HTTPError as h:
                try:
                    govde = json.loads(h.read() or b"{}")
                except ValueError:
                    govde = {}
                bekle = govde.get("parameters", {}).get("retry_after")
                if h.code == 429 and bekle is not None and deneme < 2:  # Telegram hız sınırı
                    time.sleep(bekle + 1)
                    continue
                raise RuntimeError(f"Telegram {metod}: {h.code} {govde.get('description', '')}") from None

    def gonder(self, metin: str, yanitlanan: int | None = None) -> int:
        p = {"chat_id": self.chat_id, "text": metin, "parse_mode": "HTML",
             "link_preview_options": {"is_disabled": True}}
        if yanitlanan:
            p["reply_parameters"] = {"message_id": yanitlanan, "allow_sending_without_reply": True}
        return self.cagir("sendMessage", **p)["message_id"]


def bot_olustur():
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or token == "123456:ABC...":
        return None
    return Bot(token, chat_id)


def bildir(con, ayar, bot=None, kurallar: Kurallar | None = None, bekleme: float = 1.0) -> int:
    """Uyan olayları gönderir, gönderilen mesaj sayısını döndürür. bot None ise .env'den oluşturulur."""
    bot = bot or bot_olustur()
    if not bot:
        return 0
    kurallar = kurallar or Kurallar.yukle()
    con.executescript(SEMA)
    olaylar = [o for o in export.olaylari_getir(con, ayar.export_saat) if uyuyor_mu(o, kurallar)]
    # Bildirilmiş bir olay sonradan başka bir olayla birleştiyse kayıt asıl olaya geçer (tekrar "yeni" gelmesin)
    kayitlar = {}
    for r in con.execute("SELECT * FROM bildirim"):
        kok = cluster.kok_olay(con, r["olay_id"])
        if kok not in kayitlar or r["kaynak_sayisi"] > kayitlar[kok]["kaynak_sayisi"]:
            kayitlar[kok] = r
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # İlk çalıştırmada son 72 saatin yüzlerce olayını birden göndermemek için mevcutlar "görüldü" sayılır
    if not con.execute("SELECT 1 FROM bildirim_durum WHERE ad='baslangic'").fetchone():
        con.executemany("INSERT OR REPLACE INTO bildirim (olay_id, kaynak_sayisi, zaman) VALUES (?,?,?)",
                        [(o["id"], o["kaynak_sayisi"], simdi) for o in olaylar])
        con.execute("INSERT INTO bildirim_durum VALUES ('baslangic', ?)", (simdi,))
        try:
            bot.gonder(f"✅ <b>DipWatch bildirimleri açıldı.</b>\nŞu an ölçütlerine uyan {len(olaylar)} olay var; "
                       "bundan sonra yeni ve büyüyen olaylar buraya gelecek.")
        except Exception:
            con.rollback()  # anahtar / sohbet kimliği yanlışsa başlangıç bir sonraki turda yeniden denenir
            raise
        con.commit()
        log.info("Telegram: ilk çalıştırma, %d mevcut olay görüldü sayıldı", len(olaylar))
        return 1

    gonderilecek = []
    for o in olaylar:
        k = kayitlar.get(o["id"])
        if k is None:
            gonderilecek.append((o, None))
        elif kurallar.buyume_esigi and o["kaynak_sayisi"] >= k["kaynak_sayisi"] + kurallar.buyume_esigi:
            gonderilecek.append((o, k))
    # yeni olaylar önce, sonra en çok kaynaklılar
    gonderilecek.sort(key=lambda x: (x[1] is not None, -(x[0]["onem"] or 0), -x[0]["kaynak_sayisi"]))

    gonderilen = 0
    for o, k in gonderilecek[:kurallar.tur_basina_en_fazla]:
        metin = mesaj_metni(o, kurallar, None if k is None else k["kaynak_sayisi"])
        try:
            mid = bot.gonder(metin, yanitlanan=k["mesaj_id"] if k else None)
        except Exception as h:
            log.warning("Telegram mesajı gönderilemedi (olay %s): %s", o["id"], h)
            break  # ağ / anahtar sorunu: kalanlar bir sonraki tura
        con.execute("INSERT OR REPLACE INTO bildirim (olay_id, kaynak_sayisi, mesaj_id, zaman) VALUES (?,?,?,?)",
                    (o["id"], o["kaynak_sayisi"], (k["mesaj_id"] if k and k["mesaj_id"] else mid), simdi))
        con.commit()
        gonderilen += 1
        time.sleep(bekleme)  # gruplarda dakikada ~20 mesaj sınırı var
    if len(gonderilecek) > gonderilen:
        log.info("Telegram: %d bildirim bir sonraki tura kaldı", len(gonderilecek) - gonderilen)
    return gonderilen


def chat_id_bul():
    """Bota son yazılan sohbetleri listeler (sohbet kimliğini bulmak için)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(".env içinde TELEGRAM_BOT_TOKEN yok. Önce BotFather'dan aldığın anahtarı yaz.")
        return
    guncellemeler = Bot(token, "").cagir("getUpdates")
    sohbetler = {}
    for g in guncellemeler:
        m = g.get("message") or g.get("channel_post") or g.get("my_chat_member") or {}
        if "chat" in m:
            c = m["chat"]
            sohbetler[c["id"]] = c.get("title") or " ".join(filter(None, [c.get("first_name"), c.get("last_name")]))
    if not sohbetler:
        print("Hiç mesaj bulunamadı. Telegram'da botuna bir mesaj yaz (gruptaysa bota /start yaz), sonra tekrar çalıştır.")
    for cid, ad in sohbetler.items():
        print(f"TELEGRAM_CHAT_ID={cid}    ({ad})")


def test_mesaji():
    bot = bot_olustur()
    if not bot:
        print(".env içinde TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID olmalı.")
        return
    bot.gonder("👋 <b>DipWatch</b> bağlantı testi: bu mesajı görüyorsan bildirimler çalışıyor.")
    print("Test mesajı gönderildi.")
