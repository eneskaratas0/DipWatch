"""DipWatch sitesi: data/events.json dosyasından statik HTML üretir.

Kullanım:
  python -m web                          # data/events.json -> public/
  python -m web --girdi x.json --cikti y/
Sonra public/index.html tarayıcıda açılabilir ya da herhangi bir statik sunucuya (GitHub Pages vb.) konabilir.
"""
import argparse
import logging
from pathlib import Path

from .build import KOK, olustur


def main():
    p = argparse.ArgumentParser(prog="web")
    p.add_argument("--girdi", type=Path, default=KOK / "data" / "events.json")
    p.add_argument("--cikti", type=Path, default=KOK / "public")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    olustur(a.girdi, a.cikti)


if __name__ == "__main__":
    main()
