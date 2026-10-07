"""Claude ile Türkçe olay özetleri ve diller arası olay birleştirme.

ANTHROPIC_API_KEY (veya `ant auth login` profili) yoksa bu adımlar atlanır;
olaylar yine listelenir, yalnızca Türkçe özetleri boş kalır.
"""
import json
import logging
import os

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


def istemci():
    """Kimlik bilgisi varsa Anthropic istemcisi, yoksa None."""
    try:
        import anthropic
    except ImportError:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")
            or os.path.isdir(os.path.expanduser("~/.config/anthropic"))):
        return None
    return anthropic.Anthropic()


def _json_iste(client, ayar, sistem, icerik, sema, max_tokens=4000):
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
    return json.loads(metin) if metin else None


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
        con.execute(
            """UPDATE olay SET tr_baslik=?, tr_ozet=?, bolge=?, ulkeler=?, etiketler=?, onem=?,
                 ozet_haber_sayisi = haber_sayisi WHERE id=?""",
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
            if e["yeni"] in yeni and e["mevcut"] in mevcut_k and e["yeni"] != e["mevcut"]]
