"""DipWatch teknoloji ve siber güvenlik bölümü.

Dünya genelindeki teknoloji ve siber güvenlik haberlerini (The Hacker News, BleepingComputer, Krebs on
Security, The Record, CISA, Ars Technica; liste: teknoloji/kaynaklar.yaml) RSS ile, RSS yoksa sayfayı
kazıyarak toplar. Her haber için başlık, kaynak, yayın tarihi, link, kısa özet ve kategori
(teknoloji / siber güvenlik) saklanır. Aynı haber birden fazla kaynaktan gelirse bir kez eklenir.
Veri ana toplayıcıyla aynı SQLite dosyasında (data/dipwatch.db) ayrı tablolarda durur; site için
data/teknoloji.json yazılır ve web/teknoloji.py bunu teknoloji.html sayfasına çevirir.
"""
