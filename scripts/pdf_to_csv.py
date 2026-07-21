#!/usr/bin/env python3
"""Build the per-year source CSVs from the KIISE 우수 SW 국제학술대회 PDFs.

The 2014–2020 PDFs list only 일련번호 / 약자 / 학회명 / 등급 — they carry no
대분야(AI·CS)·소분야 classification. This script:

  1. downloads each year's official PDF,
  2. extracts the conference rows with ``pdftotext -layout``,
  3. recovers 대분야/소분야 by matching each 약칭(abbreviation) against the
     2024 master CSV (``excellent_sw_conferences_2024.csv``), and
  4. writes ``data/excellent_sw_conferences_<year>.csv`` in the same 7-column
     format as the 2024 file, ready for ``scripts/build_data.py``.

Conferences that no longer appear in the 2024 list are classified from the
curated ``MANUAL`` table below; a few rows garbled by the PDF's multi-column
layout are corrected via ``OVERRIDE``. Grades (S/A) and the conference list
itself come straight from the source PDFs.

Requirements: ``pdftotext`` (poppler-utils) on PATH.

Usage:
    python scripts/pdf_to_csv.py           # download + build all years
    python scripts/build_data.py           # then refresh the dashboard data
"""
from __future__ import annotations

import csv
import re
import subprocess
import tempfile
import urllib.request
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MASTER = DATA / "excellent_sw_conferences_2024.csv"

# Official, anonymously-downloadable PDF per year.
BASE = ("https://www.kiise.or.kr/TopConferences/data/"
        "SW%EB%B6%84%EC%95%BC%EC%9A%B0%EC%88%98%ED%95%99%EC%88%A0%EB%8C%80%ED%9A%8C%EB%AA%A9%EB%A1%9D_")
YEARS = ("2014", "2016", "2018", "2020")

# ---------------------------------------------------------------- 2024 master
def na(a: str) -> str:  # normalize an abbreviation to a comparison key
    return re.sub(r"[^a-z0-9]", "", (a or "").lower())

master_abbr: dict[str, list] = {}   # norm abbr -> [(major, sub, abbr, name), ...]
with MASTER.open(encoding="utf-8-sig") as fh:
    r = csv.reader(fh); next(r)
    for row in r:
        if len(row) < 6:
            continue
        _no, major, sub, abbr, name, _grade = (c.strip() for c in row[:6])
        if abbr and major:
            master_abbr.setdefault(na(abbr), []).append((major, sub, abbr, name))

# older-form abbreviation -> 2024 abbreviation (renames / re-abbreviations)
ALIAS = {
    "eurographics": "eg", "osdi": "usenixosdi", "nsdi": "usenixnsdi",
    "fast": "usenixfast", "atc": "usenixatc", "nips": "neurips",
    "fseesec": "fse", "naaclhlt": "naacl", "pvldb": "vldb",
    "pacific": "pg", "pacificgraphics": "pg", "usenix": "usenixsecurity",
    "usenixsecuritysymposium": "usenixsecurity",
}

# conferences absent from the 2024 list, classified by hand: (major, sub, name?)
MANUAL = {
    "asrusl": ("AI", "NLP", None), "asruslt": ("AI", "NLP", None),
    "avss": ("AI", "CV", None), "bibe": ("AI", "Bio", None),
    "civr": ("AI", "CV", None), "cocoon": ("CS", "Alg", None),
    "cogsci": ("AI", "ML", None), "cosn": ("CS", "Net", None),
    "csb": ("AI", "Bio", None), "cseet": ("CS", "SE", None),
    "dcoss": ("CS", "Net", None), "ecai": ("AI", "ML", None),
    "embc": ("AI", "Bio", None), "gecco": ("AI", "ML", None),
    "grid": ("CS", "HPC", None), "hipc": ("CS", "HPC", None),
    "hipeac": ("CS", "Arch", None), "icaps": ("AI", "ML", None),
    "icdt": ("CS", "DB", None), "icip": ("AI", "CV", None),
    "iclp": ("CS", "PL", None), "icpr": ("AI", "CV", None),
    "ijcar": ("CS", "PL", None), "infovis": ("CS", "CGI", None),
    "ismm": ("CS", "PL", None), "ismvl": ("CS", "Arch", None),
    "issac": ("CS", "Alg", None), "itp": ("CS", "PL", None),
    "its": ("AI", "ML", None), "kr": ("AI", "ML",
        "International Conference on Principles of Knowledge Representation and Reasoning"),
    "nossdav": ("CS", "Net", None), "performance": ("CS", "Net", None),
    "pp": ("CS", "HPC", None), "sacmat": ("CS", "Sec", None),
    "sec": ("CS", "Sec", None), "ifipsec": ("CS", "Sec", None),
    "splash": ("CS", "PL", None), "tcc": ("CS", "Sec", None),
    "wcci": ("AI", "ML", None), "splc": ("CS", "SE",
        "International Systems and Software Product Line Conference"),
    "icsme": ("CS", "SE", None), "icsm": ("CS", "SE", None), "icmse": ("CS", "SE", None),
}

# rows garbled by the PDF's multi-column layout: (abbr, name, major, sub)
OVERRIDE = {
    "2016-S-039": ("USENIX OSDI", "USENIX Symposium on Operating Systems Design and Implementation", "CS", "OS"),
    "2016-A-134": ("NeurIPS", "Conference on Neural Information Processing Systems (spotlight/poster)", "AI", "ML"),
    "2018-S-011": ("CVPR", "Conference on Computer Vision and Pattern Recognition (oral, spotlight)", "AI", "CV"),
    "2018-S-013": ("ECCV", "European Conference on Computer Vision (oral, spotlight)", "AI", "CV"),
    "2018-S-024": ("ICML", "International Conference on Machine Learning (oral, spotlight)", "AI", "ML"),
    "2018-S-039": ("USENIX OSDI", "USENIX Symposium on Operating Systems Design and Implementation", "CS", "OS"),
    "2018-S-051": ("SIGGRAPH ASIA", "ACM SIG International Conference on Computer Graphics and Interactive Techniques (Asia)", "CS", "CGI"),
    "2018-A-056": ("ICLR", "International Conference on Learning Representations (oral, spotlight)", "AI", "ML"),
    "2020-S-041": ("USENIX OSDI", "USENIX Symposium on Operating Systems Design and Implementation", "CS", "OS"),
    "2014-S-031": ("VIS", "IEEE Visualization Conference", "CS", "CGI"),
    "2014-S-058": ("USENIX Security", "USENIX Security Symposium", "CS", "Sec"),
    "2014-A-195": ("USENIX ATC", "USENIX Annual Technical Conference", "CS", "OS"),
    "2014-A-196": ("USENIX FAST", "USENIX Conference on File and Storage Technologies", "CS", "OS"),
    "2014-A-197": ("USENIX NSDI", "USENIX Symposium on Networked Systems Design and Implementation", "CS", "Net"),
    "2014-A-198": ("USENIX Security", "USENIX Security Symposium", "CS", "Sec"),
}


def _pick(cands, name):
    """From duplicate 2024 abbr entries (e.g. FSE), pick the best name match."""
    if len(cands) == 1:
        return cands[0]
    b = set(re.findall(r"[a-z]+", (name or "").lower()))
    return max(cands, key=lambda c: len(b & set(re.findall(r"[a-z]+", c[3].lower()))))


def enrich(abbr, name):
    """Return (major, sub, abbr, name); major is None when unclassifiable."""
    lead = re.split(r"[\s(]", (abbr or "").strip())[0]        # abbr before space/paren
    base = [na(abbr), na(lead)] + [na(p) for p in re.split(r"[/+]", abbr or "")]
    keys: list[str] = []
    for k in base:                                            # expand each via ALIAS
        if k and k not in keys:
            keys.append(k)
        if k in ALIAS and ALIAS[k] not in keys:
            keys.append(ALIAS[k])
    for k in keys:
        if k in master_abbr:
            mj, sb, ca, cn = _pick(master_abbr[k], name)
            return mj, sb, ca, cn                             # canonical 2024 name wins
    for k in keys:
        if k in MANUAL:
            mj, sb, mn = MANUAL[k]
            return mj, sb, (lead or abbr), (mn or name)
    return None, None, abbr, name


# ---------------------------------------------------------------- PDF parsing
def pdftext(year: str, workdir: pathlib.Path) -> list[str]:
    pdf = workdir / f"{year}.pdf"
    urllib.request.urlretrieve(f"{BASE}{year}.pdf", pdf)
    txt = workdir / f"{year}.txt"
    subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)
    return txt.read_text(encoding="utf-8").splitlines()


def cols(rest: str) -> list[str]:
    """Split a layout line's tail into columns separated by 2+ spaces."""
    return [c for c in re.split(r"\s{2,}", rest.strip()) if c]


def parse_revised(year, lines):
    """2016/2018/2020: flat table of 일련번호 / 약자 / 학회명 (grade in the id)."""
    numre = re.compile(rf"^\s*({year}-([SA])-\d+)\b(.*)$")
    def is_num(l): return bool(numre.match(l))
    def skip(l):
        s = l.strip()
        return (not s) or s.startswith("<") or "목록" in s or s in ("비고", "약자", "학회명", "일련번호")
    abbr_re = re.compile(r"^[A-Z][A-Za-z0-9&./+-]{1,9}$")
    def abbrlike(t): return bool(abbr_re.match(t)) and sum(c.isupper() for c in t) >= 2
    def flat(s): return re.sub(r"\s+", " ", s.strip())

    nums = []                                                 # pass 1: number lines
    for i, l in enumerate(lines):
        m = numre.match(l)
        if not m:
            continue
        c = cols(m.group(3))
        rec = {"i": i, "no": m.group(1).strip(), "grade": m.group(2),
               "abbr": c[0] if c else "", "frags": []}
        if len(c) > 1:
            rec["frags"].append((i, " ".join(c[1:])))
        nums.append(rec)

    def nearest(i): return min(nums, key=lambda r: abs(r["i"] - i))
    for i, l in enumerate(lines):                             # pass 2: wrapped lines
        if is_num(l) or skip(l):
            continue
        r = nearest(i); c = cols(l)
        if not r["abbr"] and c and abbrlike(c[0]):            # centered/offset abbr
            r["abbr"] = c[0]
            if len(c) > 1:
                r["frags"].append((i, " ".join(c[1:])))
        else:
            r["frags"].append((i, flat(l)))
    return [{"no": r["no"], "grade": r["grade"], "abbr": r["abbr"],
             "name": flat(" ".join(f for _, f in sorted(r["frags"])))} for r in nums]


def parse_2014(lines):
    """2014: 최우수 목록 grouped by field header, then a flat 우수 목록."""
    s_start = next(i for i, l in enumerate(lines) if "1)" in l and "최우수" in l)
    a_start = next(i for i, l in enumerate(lines) if "2)" in l and "우수" in l)
    recs = []
    for l in lines[s_start + 1:a_start]:                      # S section
        s = l.strip()
        if not s or s.isdigit():
            continue
        m = re.match(r"^(\d+)\s+(?:\(biannual\)\s+)?(\S+)\s*(.*)$", s)
        if m:
            recs.append({"no": "", "grade": "S", "abbr": m.group(2), "name": m.group(3).strip()})
    for l in lines[a_start + 1:]:                             # A section
        s = l.strip()
        if not s or s.isdigit():
            continue
        m = re.match(r"^(\d+)\s+(\S+)\s+(.*)$", s)
        if m:
            recs.append({"no": "", "grade": "A", "abbr": m.group(2), "name": m.group(3).strip()})
    return recs


def renumber(recs, year):
    """Assign clean 2024-style ids: <year>-<grade>-<seq>."""
    cs = ca = 0
    for r in recs:
        if r["grade"] == "S":
            cs += 1; r["no"] = f"{year}-S-{cs:03d}"
        else:
            ca += 1; r["no"] = f"{year}-A-{ca:03d}"
    return recs


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        for year in YEARS:
            lines = pdftext(year, work)
            recs = parse_2014(lines) if year == "2014" else parse_revised(year, lines)
            renumber(recs, year)
            out = DATA / f"excellent_sw_conferences_{year}.csv"
            mapped = 0; unmapped = []
            with out.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["번호", "대분야", "소분야", "약칭", "학회명", "등급", "비고"])
                for r in recs:
                    note = ""
                    if r["no"] in OVERRIDE:
                        abbr, name, mj, sb = OVERRIDE[r["no"]]; mapped += 1
                    else:
                        mj, sb, abbr, name = enrich(r["abbr"], r["name"])
                        if mj:
                            mapped += 1
                        else:
                            mj, sb, note = "ETC", "ETC", "미분류"
                            unmapped.append(r["abbr"] or r["name"][:20])
                    w.writerow([r["no"], mj, sb, abbr, name, r["grade"], note])
            s = sum(1 for r in recs if r["grade"] == "S")
            print(f"{year}: {len(recs)} conferences (S={s}, A={len(recs) - s}), "
                  f"classified={mapped}, unclassified={len(unmapped)} -> {out.name}")
            if unmapped:
                print("   unclassified:", ", ".join(sorted(set(unmapped))))


if __name__ == "__main__":
    main()
