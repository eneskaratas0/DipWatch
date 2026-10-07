import yaml, urllib.request, urllib.parse, concurrent.futures as cf, json, re, sys
d = yaml.safe_load(open(__import__('pathlib').Path(__file__).with_name('sources.yaml')))['bolgeler']
GN = "https://news.google.com/rss/search?q=site:{}+when:1d&hl=en-US&gl=US&ceid=US:en"
items = []
for reg, lst in d.items():
    for s in lst:
        url = s.get('url') or GN.format(s['alan_adi'])
        items.append((reg, s['ad'], url))
def test(it):
    reg, ad, url = it
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 DipWatch/0.1'})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(400000).decode('utf-8', 'ignore')
        n = len(re.findall(r'<item[\s>]|<entry[\s>]', body))
        return (reg, ad, url, 'ok' if n else 'bos', n, '')
    except Exception as e:
        return (reg, ad, url, 'hata', 0, str(e)[:120])
with cf.ThreadPoolExecutor(16) as ex:
    res = list(ex.map(test, items))
json.dump(res, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
from collections import Counter
print(Counter(r[3] for r in res))
for r in res:
    if r[3] != 'ok': print(r[3], r[1], '|', r[5])
