"""sources.yaml'daki tüm beslemeleri (kapalılar dahil) dener: python test_feeds.py sonuc.json"""
import concurrent.futures as cf, json, sys
from collections import Counter

from collector.config import KOK, kaynaklari_yukle
from collector.fetch import cek

kaynaklar = kaynaklari_yukle(KOK / "sources.yaml", kapalilar=True)
with cf.ThreadPoolExecutor(16) as ex:
    sonuc = list(ex.map(cek, kaynaklar))
res = [(k.bolge, k.ad, k.url, "hata" if h else ("ok" if hb else "bos"), len(hb), h or "")
       for k, hb, h in sonuc]
if len(sys.argv) > 1:
    json.dump(res, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(Counter(r[3] for r in res), "toplam", len(res))
for r in res:
    if r[3] != "ok":
        print(r[3], r[1], "|", r[5])
