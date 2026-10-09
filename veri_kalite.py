"""Veri kalitesi tanı script'i: data/dipwatch.db üzerinden DipWatch toplayıcısının bilinen veri
kalitesi sorunlarını ölçer. Düzeltmelerden önce ve sonra çalıştırılıp karşılaştırılır.

Çalıştırma:
  python veri_kalite.py                               # rapor bas
  python veri_kalite.py --kaydet once.json            # rapor bas + sonucu JSON'a yaz
  python veri_kalite.py --karsilastir once.json sonra.json   # iki --kaydet çıktısından önce/sonra tablosu
"""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from collector import bolge
from collector.fetch import baslik_normalle, gecersiz_baslik_mi

KOK = Path(__file__).resolve().parent


def _con(yol):
    con = sqlite3.connect(yol)
    con.row_factory = sqlite3.Row
    return con


def haber_olmayan_satirlar(con):
    satirlar = con.execute("SELECT id, kaynak, baslik FROM haber").fetchall()
    kotu = [r for r in satirlar if gecersiz_baslik_mi(r["baslik"])]
    return len(kotu), len(satirlar), kotu[:10]


def ayni_haber_tekrarlari(con):
    satirlar = con.execute("SELECT kaynak, baslik FROM haber").fetchall()
    sayac = Counter((r["kaynak"], baslik_normalle(r["baslik"])) for r in satirlar)
    tekrarlar = {k: v for k, v in sayac.items() if v > 1}
    fazla_satir = sum(v - 1 for v in tekrarlar.values())
    return len(tekrarlar), fazla_satir, sorted(tekrarlar.items(), key=lambda x: -x[1])[:10]


def yanlis_bolge_orani(con):
    """Aktif olaylardan, içerikte net bir coğrafi işaret olup da ESKİ yöntemle (kaynağın/beslemenin
    bölgesi -- export.py'nin düzeltmeden önceki hali) atanan bölgeyle çelişenlerin oranı; aynı anda
    YENİ yöntemle (bolge.tahmin_et -- şu anki export.py) atanan bölgeyle çelişen oranı da hesaplanır.
    (Claude bir bölge atamışsa her iki yöntem de onu kullanır, ikisi de çelişkisiz sayılır.) Konu
    coğrafi değilse (Nobel, BM genel) içerikte ülke adı geçse de çelişki sayılmaz."""
    olaylar = con.execute(
        "SELECT id, bolge FROM olay WHERE birlesti IS NULL AND haber_sayisi > 0").fetchall()
    eski_celisen = yeni_celisen = net_isaretli = 0
    eski_ornek, yeni_ornek = [], []
    for o in olaylar:
        haberler = [dict(r) for r in con.execute(
            "SELECT kaynak, bolge, baslik, ozet FROM haber WHERE olay_id=?", (o["id"],))]
        if not haberler:
            continue
        eski_kayitli = o["bolge"] or bolge.kaynak_tahmini(haberler)
        yeni_kayitli = o["bolge"] or bolge.tahmin_et(haberler)
        metinler = [f"{h['baslik']} {h.get('ozet') or ''}" for h in haberler]
        if bolge.KURESEL_ZORUNLU.search(" ".join(metinler)):
            continue
        oylar = Counter()
        for m in metinler:
            oylar.update(bolge._icerik_oylari(m))
        if not oylar:
            continue
        en_cok = oylar.most_common()
        if len(en_cok) > 1 and en_cok[0][1] == en_cok[1][1]:
            continue  # eşitlik: net işaret yok
        net_isaretli += 1
        icerik_bolgesi = en_cok[0][0]
        if icerik_bolgesi != eski_kayitli:
            eski_celisen += 1
            if len(eski_ornek) < 10:
                eski_ornek.append((o["id"], eski_kayitli, icerik_bolgesi, haberler[0]["baslik"][:70]))
        if icerik_bolgesi != yeni_kayitli:
            yeni_celisen += 1
            if len(yeni_ornek) < 10:
                yeni_ornek.append((o["id"], yeni_kayitli, icerik_bolgesi, haberler[0]["baslik"][:70]))
    eski_oran = eski_celisen / net_isaretli if net_isaretli else 0.0
    yeni_oran = yeni_celisen / net_isaretli if net_isaretli else 0.0
    return dict(eski_celisen=eski_celisen, yeni_celisen=yeni_celisen, net_isaretli=net_isaretli,
                eski_oran=eski_oran, yeni_oran=yeni_oran, eski_ornek=eski_ornek, yeni_ornek=yeni_ornek)


def konu_disi_drift(con):
    """Embedding'i olan, en az 3 kaynaklı olaylarda, merkez vektöre belirgin uzak kalan (muhtemelen
    konu dışı) haberlerin sayısı -- kümenin konudan kaymasının (bkz. cluster.py) bir göstergesi."""
    if np is None:
        return 0, 0, []
    olaylar = con.execute(
        "SELECT id FROM olay WHERE birlesti IS NULL AND kaynak_sayisi >= 3").fetchall()
    sapan, taranan, ornekler = 0, 0, []
    for o in olaylar:
        satirlar = con.execute(
            "SELECT kaynak, baslik, vektor FROM haber WHERE olay_id=? AND vektor IS NOT NULL",
            (o["id"],)).fetchall()
        if len(satirlar) < 3:
            continue
        vs = np.stack([np.frombuffer(r["vektor"], dtype=np.float32) for r in satirlar])
        merkez = vs.mean(axis=0)
        merkez /= np.maximum(np.linalg.norm(merkez), 1e-9)
        benzerlik = vs @ merkez
        taranan += len(satirlar)
        for r, b in zip(satirlar, benzerlik):
            if b < 0.20:
                sapan += 1
                if len(ornekler) < 10:
                    ornekler.append((o["id"], r["kaynak"], r["baslik"][:70], float(b)))
    return sapan, taranan, ornekler


def bolunmus_konular(con, esik=0.90, pencere_saat=72):
    """Son `pencere_saat` saatte güncellenmiş olayların merkez (gömme) vektörlerini birbirine
    benzerliğe göre kümeler; eşik üstü kalan farklı olay id'leri aynı (yakın zamanlı, somut) konunun
    kaç olaya bölündüğünü gösterir (bağlı bileşenler). Pencere, gerçek birleştirme adımının
    (embed.birlestirme_onerileri) baktığı aralıkla aynıdır -- aksi halde "Gazze savaşı" gibi yıllara
    yayılan, meşru biçimde ayrı kalması gereken binlerce olay tek bir büyük kümeye düşer. Eşik de
    üretimdeki gomme_esigi'nden (0.70) kasıtlı olarak yüksek tutulmuştur: bu fonksiyon tüm aktif
    olayları birbirine bağlı bileşen olarak (geçişli) kümeler, üretimdeki algoritma ise her olay için
    yalnızca EN YAKIN komşuya bakar (geçişli değil) -- 0.70-0.80 arası birçok "aynı geniş temada,
    meşru biçimde ayrı" haberi (ör. yıllardır süren bir savaşın farklı günlerindeki haberleri) tek
    kümeye toplayıp gerçek tekrar/bölünme sayısını büyütür. 0.90 gerçek tekrarlara (bu veride 0.83-0.90
    arası ölçülen Kimya Nobeli TR/EN ve Trump'ın "ödülü hak ediyorum" haberleri gibi) daha yakındır."""
    if np is None:
        return [], 0
    sinir = (datetime.now(timezone.utc) - timedelta(hours=pencere_saat)).isoformat()
    satirlar = con.execute(
        """SELECT h.olay_id, h.vektor FROM haber h JOIN olay o ON o.id=h.olay_id
           WHERE o.birlesti IS NULL AND o.haber_sayisi > 0 AND o.guncelleme >= ?
             AND h.vektor IS NOT NULL""", (sinir,)).fetchall()
    toplam = {}
    for r in satirlar:
        v = np.frombuffer(r["vektor"], dtype=np.float32)
        toplam[r["olay_id"]] = toplam.get(r["olay_id"], 0) + v
    if len(toplam) < 2:
        return [], len(toplam)
    idler = list(toplam)
    merkez = np.stack([toplam[i] for i in idler])
    merkez /= np.maximum(np.linalg.norm(merkez, axis=1, keepdims=True), 1e-9)
    benz = merkez @ merkez.T

    ebeveyn = {i: i for i in idler}

    def bul(x):
        while ebeveyn[x] != x:
            x = ebeveyn[x]
        return x

    for i in range(len(idler)):
        for j in range(i + 1, len(idler)):
            if benz[i, j] >= esik:
                a, b = bul(idler[i]), bul(idler[j])
                if a != b:
                    ebeveyn[a] = b
    kumeler = defaultdict(list)
    for i in idler:
        kumeler[bul(i)].append(i)
    bolunmus = [v for v in kumeler.values() if len(v) > 1]
    return bolunmus, len(idler)


def rapor(db_yolu):
    con = _con(db_yolu)
    toplam_olay = con.execute(
        "SELECT COUNT(*) FROM olay WHERE birlesti IS NULL AND haber_sayisi > 0").fetchone()[0]
    kotu_n, toplam_haber, kotu_ornek = haber_olmayan_satirlar(con)
    tekrar_n, tekrar_fazla, tekrar_ornek = ayni_haber_tekrarlari(con)
    bg = yanlis_bolge_orani(con)
    sapan, taranan, drift_ornek = konu_disi_drift(con)
    bolunmus, pencere_olay_n = bolunmus_konular(con)

    print(f"== Veri kalitesi tanısı: {db_yolu} ==")
    print(f"toplam haber: {toplam_haber} · aktif olay: {toplam_olay} "
          f"(son 72 saatte güncellenen, vektörlü: {pencere_olay_n})")
    print(f"haber olmayan satır: {kotu_n} ({kotu_n / toplam_haber:.2%})")
    for r in kotu_ornek:
        print(f"   - [{r['kaynak']}] {r['baslik']!r}")
    print(f"aynı kaynak+başlık tekrarı: {tekrar_n} grup, {tekrar_fazla} fazladan satır")
    for (kaynak, _), n in tekrar_ornek[:5]:
        print(f"   - {kaynak} x{n}")
    print(f"tahmini yanlış bölgeli olay oranı (ESKİ yöntem, kaynağın bölgesi): {bg['eski_oran']:.1%}  "
          f"({bg['eski_celisen']}/{bg['net_isaretli']})")
    for oid, kayitli, icerik, b in bg["eski_ornek"][:5]:
        print(f"   - olay {oid}: kayıtlı={kayitli} içerik={icerik}  {b!r}")
    print(f"tahmini yanlış bölgeli olay oranı (YENİ yöntem, içerikten çıkarım): {bg['yeni_oran']:.1%}  "
          f"({bg['yeni_celisen']}/{bg['net_isaretli']})")
    for oid, kayitli, icerik, b in bg["yeni_ornek"][:5]:
        print(f"   - olay {oid}: kayıtlı={kayitli} içerik={icerik}  {b!r}")
    print(f"konu dışı (merkezden belirgin uzak) haber: {sapan}/{taranan}")
    for oid, kaynak, b, benz in drift_ornek[:5]:
        print(f"   - olay {oid} [{kaynak}] benzerlik={benz:.2f}  {b!r}")
    print(f"aynı konunun birden fazla olaya bölündüğü grup sayısı: {len(bolunmus)}")
    for grup in sorted(bolunmus, key=lambda g: -len(g))[:5]:
        basliklar = [con.execute("SELECT baslik FROM haber WHERE olay_id=? LIMIT 1", (o,)).fetchone()[0][:50]
                     for o in grup]
        print(f"   - {len(grup)} olay: {grup} :: {basliklar}")
    con.close()
    return dict(toplam_haber=toplam_haber, aktif_olay=toplam_olay, kotu_baslik=kotu_n,
                tekrar_grup=tekrar_n, tekrar_fazla=tekrar_fazla,
                yanlis_bolge_oran_eski=bg["eski_oran"], yanlis_bolge_oran_yeni=bg["yeni_oran"],
                net_isaretli=bg["net_isaretli"], drift_sayi=sapan,
                drift_taranan=taranan, bolunmus_grup=len(bolunmus))


def karsilastir(once_yol, sonra_yol):
    once = json.loads(Path(once_yol).read_text(encoding="utf-8"))
    sonra = json.loads(Path(sonra_yol).read_text(encoding="utf-8"))
    anahtarlar = [
        ("kotu_baslik", "haber olmayan satır"),
        ("tekrar_grup", "tekrarlı başlık grubu"),
        ("tekrar_fazla", "tekrardan fazladan satır"),
        ("yanlis_bolge_oran_eski", "yanlış bölge oranı (eski yöntem)"),
        ("yanlis_bolge_oran_yeni", "yanlış bölge oranı (yeni yöntem)"),
        ("drift_sayi", "konu dışı (merkezden uzak) haber"),
        ("bolunmus_grup", "aynı konunun bölündüğü grup sayısı"),
    ]
    print(f"{'metrik':45} {'önce':>12} {'sonra':>12}")
    for k, ad in anahtarlar:
        o, s = once.get(k), sonra.get(k)
        of = f"{o:.1%}" if isinstance(o, float) else o
        sf = f"{s:.1%}" if isinstance(s, float) else s
        print(f"{ad:45} {of!s:>12} {sf!s:>12}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(KOK / "data" / "dipwatch.db"))
    p.add_argument("--kaydet", help="Sonucu JSON olarak bu dosyaya yaz")
    p.add_argument("--karsilastir", nargs=2, metavar=("ONCE_JSON", "SONRA_JSON"),
                   help="İki --kaydet çıktısını karşılaştırıp önce/sonra tablosu bas")
    a = p.parse_args()
    if a.karsilastir:
        return karsilastir(*a.karsilastir)
    sonuc = rapor(a.db)
    if a.kaydet:
        Path(a.kaydet).write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
