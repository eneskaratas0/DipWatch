"""Türkçe olay özetleri ve diller arası olay birleştirme (Claude ya da ücretsiz bir LLM ile).

Sağlayıcı seçimi (bkz. istemci()): DIPWATCH_LLM=claude|gemini|groq ile zorlanabilir; verilmezse
ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY sırasıyla aranır. Gemini ve Groq ücretsiz katmanla
çalışır; ikisinin de anahtarı varsa Gemini kotası dolunca Groq'a geçilir. Hiçbiri yoksa bu adımlar
atlanır; olaylar yine listelenir, yalnızca Türkçe özetleri boş kalır.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("dipwatch.ozet")

BOLGELER = ["kuresel", "orta_dogu", "rusya_ukrayna_kafkasya", "avrupa", "asya_pasifik",
            "afrika", "amerika", "turkiye"]

OZET_SISTEM = """Sen DipWatch için çalışan bir uluslararası ilişkiler editörüsün. Okurun Türkçe konuşan bir \
uluslararası ilişkiler öğrencisi. Sana aynı olayı anlatan birkaç haberin başlık ve kısa açıklaması verilecek.
Görevin:
- Olay için kısa, tarafsız bir Türkçe başlık yazmak.
- 2-4 cümlelik Türkçe özet yazmak: ne oldu, kim, nerede, neden önemli. Yalnızca verilen haberlerdeki \
bilgiyi kullan; tahmin ekleme. Kaynaklar birbiriyle çelişiyorsa ya da bir taraf farklı bir anlatı \
sunuyorsa bunu açıkça belirt (örneğin "İsrail basını ... derken Arap basını ...").
- Olayın ana bölgesini, ilgili ülkeleri ve 1 (rutin) ile 5 (büyük kriz, savaş, ilk kez yaşanan diplomatik \
kırılma) arasında bir önem puanını vermek."""

OZET_SEMA = {
    "type": "object",
    "properties": {
        "baslik": {"type": "string"},
        "ozet": {"type": "string"},
        "bolge": {"type": "string", "enum": BOLGELER},
        "ulkeler": {"type": "array", "items": {"type": "string"}},
        "etiketler": {"type": "array", "items": {"type": "string"}},
        "onem": {"type": "integer"},
    },
    "required": ["baslik", "ozet", "bolge", "ulkeler", "etiketler", "onem"],
    "additionalProperties": False,
}

BIRLESTIR_SISTEM = """Sana iki liste verilecek: YENİ olaylar ve MEVCUT olaylar (her biri bir numara ve \
başlıklardan oluşur, başlıklar farklı dillerde olabilir; YENİ olaylar MEVCUT listesinde de yer alır). \
Bir YENİ olay, kendisinden farklı numaralı bir MEVCUT olayla aynı somut gelişmeyi anlatıyorsa (aynı saldırı, aynı görüşme, aynı açıklama) eşleştir. Sadece aynı konuyla ilgili \
olmak yetmez; emin değilsen eşleştirme."""

BIRLESTIR_SEMA = {
    "type": "object",
    "properties": {
        "eslesmeler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"yeni": {"type": "integer"}, "mevcut": {"type": "integer"}},
                "required": ["yeni", "mevcut"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["eslesmeler"],
    "additionalProperties": False,
}


# OpenAI uyumlu ücretsiz sağlayıcılar. Model, DIPWATCH_<AD>_MODEL ile değiştirilebilir.
# aralik: iki istek arası en az saniye (ücretsiz katmanların dakikalık sınırına takılmamak için).
UCRETSIZ = {
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "anahtar": "GEMINI_API_KEY", "model": "gemini-flash-lite-latest", "aralik": 7},
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions",
             "anahtar": "GROQ_API_KEY", "model": "openai/gpt-oss-120b", "aralik": 3},
}


class UcretsizIstemci:
    """OpenAI uyumlu /chat/completions ucu (Gemini, Groq). Ek paket gerektirmez.
    429 (kota/hız sınırı) gelirse sağlayıcı bir süre dinlendirilir; zincirdeki sıradaki denenir."""

    # Ücretsiz kotayı korumak için diller arası birleştirme varsayılan olarak kapalı: bunu zaten
    # anahtarsız çalışan gömme modeli (embed.py) yapıyor. DIPWATCH_LLM_BIRLESTIRME=1 ile açılır.
    @property
    def birlestirme(self):
        return os.environ.get("DIPWATCH_LLM_BIRLESTIRME", "0") == "1"

    def __init__(self, saglayicilar: list[tuple[str, dict, str]]):
        # (ad, ayar, anahtar) listesi; sırayla denenir
        self.saglayicilar = saglayicilar
        self._son_istek: dict[str, float] = {}
        self._dinlen: dict[str, float] = {}

    def json_iste(self, sistem, icerik, sema, max_tokens):
        sistem = (sistem + "\n\nYanıtın YALNIZCA şu JSON şemasına uyan tek bir JSON nesnesi olsun, "
                  "başka metin yazma:\n" + json.dumps(sema, ensure_ascii=False))
        for ad, ayar, anahtar in self.saglayicilar:
            if time.time() < self._dinlen.get(ad, 0):
                continue
            bekle = self._son_istek.get(ad, 0) + ayar["aralik"] - time.time()
            if bekle > 0:
                time.sleep(bekle)
            self._son_istek[ad] = time.time()
            govde = {
                "model": os.environ.get(f"DIPWATCH_{ad.upper()}_MODEL", ayar["model"]),
                "messages": [{"role": "system", "content": sistem}, {"role": "user", "content": icerik}],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
            istek = urllib.request.Request(
                ayar["url"], data=json.dumps(govde).encode(), method="POST",
                headers={"Authorization": f"Bearer {anahtar}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(istek, timeout=90) as r:
                    yanit = json.load(r)
            except urllib.error.HTTPError as e:
                ayrinti = e.read()[:300].decode("utf-8", "replace")
                if e.code == 429:
                    # Günlük kota mı dakikalık sınır mı ayırt etmek sağlayıcıya göre değişiyor;
                    # 15 dk dinlendirmek ikisinde de kotayı boşa harcamaz.
                    self._dinlen[ad] = time.time() + 900
                    log.warning("%s kota/hız sınırı (429); 15 dk dinlendiriliyor", ad)
                else:
                    log.warning("%s isteği başarısız (%s): %s", ad, e.code, ayrinti)
                continue
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                log.warning("%s geçici hata: %s", ad, e)
                continue
            try:
                metin = yanit["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                log.warning("%s yanıtı beklenmedik biçimde", ad)
                continue
            if metin:
                return metin
        return None


def istemci():
    """Kullanılabilir LLM istemcisi (Anthropic ya da UcretsizIstemci), yoksa None."""
    secim = os.environ.get("DIPWATCH_LLM", "").strip().lower()
    if secim in ("", "claude"):
        c = _claude_istemci()
        if c or secim == "claude":
            return c
    adlar = [secim] if secim in UCRETSIZ else list(UCRETSIZ)
    zincir = [(ad, UCRETSIZ[ad], os.environ[UCRETSIZ[ad]["anahtar"]])
              for ad in adlar if os.environ.get(UCRETSIZ[ad]["anahtar"])]
    if not zincir:
        return None
    log.info("Özet sağlayıcısı: %s", " -> ".join(ad for ad, _, _ in zincir))
    return UcretsizIstemci(zincir)


def _claude_istemci():
    try:
        import anthropic
    except ImportError:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return None
    return anthropic.Anthropic()


def _sema_uygun(veri, sema) -> bool:
    """Ücretsiz modeller şemaya her zaman uymuyor: zorunlu alanları ve türleri kabaca denetler."""
    if not isinstance(veri, dict):
        return False
    turler = {"string": str, "integer": (int, float), "array": list, "object": dict}
    for alan in sema["required"]:
        if alan not in veri or not isinstance(veri[alan], turler[sema["properties"][alan]["type"]]):
            return False
    return True


def _json_iste(client, ayar, sistem, icerik, sema, max_tokens=4000):
    if isinstance(client, UcretsizIstemci):
        metin = client.json_iste(sistem, icerik, sema, max_tokens)
        if not metin:
            return None
        metin = metin.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            veri = json.loads(metin)
        except json.JSONDecodeError as e:
            log.warning("LLM yanıtı JSON olarak ayrıştırılamadı: %s", e)
            return None
        if not _sema_uygun(veri, sema):
            log.warning("LLM yanıtı şemaya uymuyor; atlandı")
            return None
        return veri
    import anthropic
    try:
        r = client.beta.messages.create(
            model=ayar.model,
            max_tokens=max_tokens,
            system=sistem,
            messages=[{"role": "user", "content": icerik}],
            output_config={"effort": ayar.efor, "format": {"type": "json_schema", "schema": sema}},
            # Güvenlik sınıflandırıcısı reddederse istek sunucu tarafında başka modelle yeniden denenir
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        log.warning("Claude hız sınırı; bu tur atlandı")
        return None
    except (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.PermissionDeniedError,
            anthropic.NotFoundError) as e:
        log.error("Claude isteği reddedildi: %s", e)
        return None
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.warning("Claude geçici hata: %s", e)
        return None
    if r.stop_reason == "refusal":
        log.warning("Claude isteği reddetti")
        return None
    metin = next((b.text for b in r.content if b.type == "text"), None)
    if not metin:
        return None
    try:
        return json.loads(metin)
    except json.JSONDecodeError as e:
        log.warning("Claude yanıtı JSON olarak ayrıştırılamadı: %s", e)
        return None


def _haber_metni(haberler):
    satir = []
    for h in haberler:
        s = f"- [{h['kaynak']}] {h['baslik']}"
        if h["ozet"] and h["ozet"] != h["baslik"]:
            s += f"\n  {h['ozet'][:400]}"
        satir.append(s)
    return "\n".join(satir)


def ozetle(con, ayar, client) -> int:
    """Haber sayısı değişmiş olayları özetler; özetlenen olay sayısını döndürür."""
    olaylar = con.execute(
        """SELECT id FROM olay WHERE birlesti IS NULL AND kaynak_sayisi >= ?
             AND haber_sayisi != ozet_haber_sayisi
           ORDER BY kaynak_sayisi DESC, guncelleme DESC LIMIT ?""",
        (ayar.ozet_min_kaynak, ayar.ozet_max_olay_tur)).fetchall()
    n = 0
    for o in olaylar:
        haberler = con.execute(
            "SELECT kaynak, baslik, ozet FROM haber WHERE olay_id = ? ORDER BY yayin LIMIT 25",
            (o["id"],)).fetchall()
        sonuc = _json_iste(client, ayar, OZET_SISTEM, _haber_metni(haberler), OZET_SEMA)
        if not sonuc:
            continue
        if sonuc["bolge"] not in BOLGELER:
            sonuc["bolge"] = None  # dışa aktarımda bolge.py tahmini kullanılır
        con.execute(
            """UPDATE olay SET tr_baslik=?, tr_ozet=?, bolge=?, ulkeler=?, etiketler=?, onem=?,
                 ozet_turu='llm', ozet_haber_sayisi = haber_sayisi WHERE id=?""",
            (sonuc["baslik"], sonuc["ozet"], sonuc["bolge"],
             json.dumps(sonuc["ulkeler"], ensure_ascii=False),
             json.dumps(sonuc["etiketler"], ensure_ascii=False),
             max(1, min(5, int(sonuc["onem"]))), o["id"]))
        con.commit()
        n += 1
    return n


def birlestirme_onerileri(con, ayar, client, yeni_olaylar: list[int]) -> list[tuple[int, int]]:
    """Bu turda açılan olaylardan, mevcut bir olayla aynı olanları (yeni, mevcut) çiftleri olarak döndürür."""
    if not yeni_olaylar:
        return []

    def basliklar(oid):
        return " | ".join(r["baslik"] for r in con.execute(
            "SELECT baslik FROM haber WHERE olay_id=? LIMIT 3", (oid,)))

    yeni = set(yeni_olaylar[:80])
    # Yeni olaylar birbiriyle de eşleşebilsin diye mevcut listeye onlar da dahil
    mevcut = [r["id"] for r in con.execute(
        """SELECT id FROM olay WHERE birlesti IS NULL AND haber_sayisi > 0
           ORDER BY guncelleme DESC LIMIT 200""")]
    if not mevcut:
        return []
    icerik = ("YENİ:\n" + "\n".join(f"{i}: {basliklar(i)}" for i in yeni)
              + "\n\nMEVCUT:\n" + "\n".join(f"{i}: {basliklar(i)}" for i in mevcut))
    sonuc = _json_iste(client, ayar, BIRLESTIR_SISTEM, icerik, BIRLESTIR_SEMA)
    if not sonuc:
        return []
    mevcut_k = set(mevcut)
    return [(e["yeni"], e["mevcut"]) for e in sonuc["eslesmeler"]
            if isinstance(e, dict) and e.get("yeni") in yeni and e["mevcut"] in mevcut_k and e["yeni"] != e["mevcut"]]
