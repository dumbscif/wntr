#!/usr/bin/env python3
"""Build the compact offline gazetteer (scraper/gazetteer.tsv) from GeoNames.

Data: GeoNames (https://www.geonames.org/), CC BY 4.0. Run once; the result is
committed so GitHub Actions never needs to download it. Re-run any time:
    python scraper/build_gazetteer.py
"""
import csv, io, os, re, sys, zipfile
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://download.geonames.org/export/dump/"
UA = {"User-Agent": "WNTR-UFO-Archive gazetteer builder"}

def fetch(name):
    r = requests.get(BASE + name, headers=UA, timeout=120)
    r.raise_for_status()
    return r.content

def non_latin(s):
    return any(ord(c) > 0x24F for c in s)

def main():
    csv.field_size_limit(sys.maxsize)
    z = zipfile.ZipFile(io.BytesIO(fetch("cities5000.zip")))
    text = z.read("cities5000.txt").decode("utf-8")
    out = []
    for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        gid, name, ascii_, alts, lat, lon, fclass, fcode, cc, _cc2, a1 = row[:11]
        pop = int(row[14] or 0)
        tz = row[17]
        extra = set()
        for a in alts.split(","):
            a = a.strip()
            if not a or len(a) < 2 or a in (name, ascii_):
                continue
            # keep native-script names (CJK, Cyrillic, Hangul, Arabic, Greek...) for bigger
            # cities, plus accented Latin spellings, so non-English headlines can match.
            if non_latin(a) and pop >= 50000:
                extra.add(a)
            elif not non_latin(a) and a.lower() != ascii_.lower() and pop >= 300000 and re.search(r"[^\x00-\x7f]", a):
                extra.add(a)
        out.append([gid, name, ascii_, "|".join(sorted(extra)), f"{float(lat):.4f}", f"{float(lon):.4f}", cc, a1, str(pop), tz])
    with open(os.path.join(HERE, "gazetteer.tsv"), "w", encoding="utf-8") as f:
        f.write("# GeoNames cities5000 (CC BY 4.0) - id name ascii altnames lat lon cc admin1 pop tz\n")
        for r in out:
            f.write("\t".join(x.replace("\t", " ") for x in r) + "\n")
    a1 = fetch("admin1CodesASCII.txt").decode("utf-8")
    with open(os.path.join(HERE, "admin1.tsv"), "w", encoding="utf-8") as f:
        f.write(a1)
    ci = fetch("countryInfo.txt").decode("utf-8")
    with open(os.path.join(HERE, "countries.tsv"), "w", encoding="utf-8") as f:
        for line in ci.splitlines():
            if line.startswith("#"):
                continue
            p = line.split("\t")
            if len(p) > 4:
                f.write(f"{p[0]}\t{p[4]}\t{p[8]}\n")  # iso2, name, continent
    print("gazetteer rows:", len(out))

if __name__ == "__main__":
    main()
