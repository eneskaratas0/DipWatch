"""SQLite deposu: haberler, olaylar, feed sağlığı."""
import sqlite3
from pathlib import Path

SEMA = """
CREATE TABLE IF NOT EXISTS haber (
    id INTEGER PRIMARY KEY,
    link TEXT UNIQUE,
    kaynak TEXT, bolge TEXT, dil TEXT, tur TEXT,
    baslik TEXT, ozet TEXT,
    baslik_norm TEXT,          -- küçük harf+noktalamasız başlık: aynı kaynaktan tekrarı yakalamak için
    icerik_turu TEXT DEFAULT 'haber',  -- 'haber' | 'analiz' | 'canli', bkz. fetch.icerik_turu
    yayin TEXT,              -- ISO UTC
    eklenme TEXT,
    olay_id INTEGER REFERENCES olay(id),
    vektor BLOB               -- başlığın çok dilli gömme vektörü (float32), bkz. embed.py
);
CREATE INDEX IF NOT EXISTS haber_olay ON haber(olay_id);
CREATE INDEX IF NOT EXISTS haber_yayin ON haber(yayin);

CREATE TABLE IF NOT EXISTS olay (
    id INTEGER PRIMARY KEY,
    olusma TEXT, guncelleme TEXT,
    haber_sayisi INTEGER DEFAULT 0,
    kaynak_sayisi INTEGER DEFAULT 0,
    -- Claude'un yazdığı alanlar (yoksa NULL)
    tr_baslik TEXT, tr_ozet TEXT, bolge TEXT, ulkeler TEXT, etiketler TEXT, onem INTEGER,
    ozet_haber_sayisi INTEGER DEFAULT 0,   -- özet yazıldığında kaç haber vardı
    ozet_turu TEXT,                        -- 'llm' | 'ceviri' (LLM kotası dolunca makine çevirisi, bkz. ceviri.py)
    birlesti INTEGER REFERENCES olay(id)    -- başka olaya katıldıysa
);

CREATE TABLE IF NOT EXISTS feed_durum (
    ad TEXT PRIMARY KEY, url TEXT,
    son_deneme TEXT, son_basari TEXT,
    ardisik_hata INTEGER DEFAULT 0,
    son_oge INTEGER DEFAULT 0,
    hata TEXT
);
"""


def baglan(yol: Path) -> sqlite3.Connection:
    yol.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(yol)
    con.row_factory = sqlite3.Row
    con.executescript(SEMA)
    # eski veritabanlarına sonradan eklenen sütunlar
    sutunlar = {r[1] for r in con.execute("PRAGMA table_info(haber)")}
    if "vektor" not in sutunlar:
        con.execute("ALTER TABLE haber ADD COLUMN vektor BLOB")
    if "baslik_norm" not in sutunlar:
        con.execute("ALTER TABLE haber ADD COLUMN baslik_norm TEXT")
    if "icerik_turu" not in sutunlar:
        con.execute("ALTER TABLE haber ADD COLUMN icerik_turu TEXT DEFAULT 'haber'")
    if "ozet_turu" not in {r[1] for r in con.execute("PRAGMA table_info(olay)")}:
        con.execute("ALTER TABLE olay ADD COLUMN ozet_turu TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS haber_kaynak_baslik ON haber(kaynak, baslik_norm)")
    return con
