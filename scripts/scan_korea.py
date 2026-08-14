#!/usr/bin/env python3
"""Weekly radar: scan official conference sites for Korea/Japan-hosting signals
and propose them as ready-to-merge additions.

주요 학회 공식 사이트를 가져와 한국·일본 개최 관련 키워드(Seoul·COEX·Tokyo·
Osaka …)를 훑고, *새로* 발견된 학회는 후보 항목(국가 포함)으로 만들어
data/korea_conferences.json 에 채워 넣는다. GitHub Actions 가 이 변경으로
**자동 PR** 을 열며, 사람은 PR 을 검토한 뒤 머지만 하면 라이브 대시보드에
반영된다(반자동). 일본을 포함하는 이유는 한국에서 비행기로 평균 2시간 내외라
가까워 해외 출장 부담이 적기 때문이다.

- 검증 안 된 정보가 곧바로 게시되지 않도록 PR 이 검수 게이트 역할을 한다.
  자동 추출한 항목은 needsReview=true 로 표시되어 대시보드에서 "검토중"으로 보인다.
- 개최지·개최일은 페이지에서 최선을 다해 추출하되, 실패하면 비워 두고(대시보드는
  "미정"으로 표시) PR 본문에 "확인 필요"로 명시한다. 마감일은 자동 추출하지 않는다.
- 이미 등록된 학회(items)와 이미 제안한 신호(data/korea_scan_state.json)는
  건너뛰므로 같은 PR 이 반복 생성되지 않는다.
- 연도가 URL 에 들어가는(templated) 학회만 후보 항목을 만든다. AAAI·IJCAI 같은
  단일 랜딩 페이지 학회는 월간 점검 이슈(scripts/check_korea.py)에서 다룬다.
- 사이트가 봇을 차단(403 등)하면 해당 사이트만 건너뛴다.

수동 실행:

  python3 scripts/scan_korea.py --propose --pr-body /tmp/pr-body.md
"""
import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "korea_conferences.json"
STATE = ROOT / "data" / "korea_scan_state.json"

# (약칭, URL 템플릿) — {year} 가 스캔 연도로 치환되는 학회만 후보 항목을 만든다.
SOURCES = [
    ("ICML", "https://icml.cc/Conferences/{year}"),
    ("ICLR", "https://iclr.cc/Conferences/{year}"),
    ("NeurIPS", "https://neurips.cc/Conferences/{year}"),
    ("CVPR", "https://cvpr.thecvf.com/Conferences/{year}"),
    ("ICCV", "https://iccv.thecvf.com/Conferences/{year}"),
    ("ECCV", "https://eccv.ecva.net/Conferences/{year}"),
    ("ACL", "https://{year}.aclweb.org/"),
    ("EMNLP", "https://{year}.emnlp.org/"),
    ("NAACL", "https://{year}.naacl.org/"),
    ("ICASSP", "https://{year}.ieeeicassp.org/"),
    ("INTERSPEECH", "https://interspeech{year}.org/"),
    ("KDD", "https://kdd{year}.kdd.org/"),
    ("NDSS", "https://www.ndss-symposium.org/ndss{year}/"),
    ("ICRA", "https://{year}.ieee-icra.org/"),
    ("ACCV", "https://accv{year}.org/"),
]

# 후보 항목의 학회 정식 명칭
CONF_NAMES = {
    "ICML": "International Conference on Machine Learning",
    "ICLR": "International Conference on Learning Representations",
    "NeurIPS": "Conference on Neural Information Processing Systems",
    "CVPR": "IEEE/CVF Conference on Computer Vision and Pattern Recognition",
    "ICCV": "IEEE/CVF International Conference on Computer Vision",
    "ECCV": "European Conference on Computer Vision",
    "ACL": "Annual Meeting of the Association for Computational Linguistics",
    "EMNLP": "Conference on Empirical Methods in Natural Language Processing",
    "NAACL": "Annual Conference of the Nations of the Americas Chapter of the ACL",
    "ICASSP": "IEEE International Conference on Acoustics, Speech and Signal Processing",
    "INTERSPEECH": "Interspeech",
    "KDD": "ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
    "NDSS": "Network and Distributed System Security Symposium",
    "ICRA": "IEEE International Conference on Robotics and Automation",
    "ACCV": "Asian Conference on Computer Vision",
}

# 개최장 키워드 → (국가, 개최장(venue), 도시 KO, 도시 EN)
VENUE_MAP = {
    "icc jeju": ("KR", "ICC Jeju", "제주", "Jeju"),
    "coex": ("KR", "COEX", "서울", "Seoul"),
    "bexco": ("KR", "BEXCO", "부산", "Busan"),
    "kintex": ("KR", "KINTEX", "고양", "Goyang"),
    "songdo": ("KR", "Songdo Convensia", "인천", "Incheon"),
}
# 도시 키워드 → (국가, 도시 KO, 도시 EN)
CITY_MAP = {
    # 한국
    "seoul": ("KR", "서울", "Seoul"),
    "busan": ("KR", "부산", "Busan"),
    "jeju": ("KR", "제주", "Jeju"),
    "incheon": ("KR", "인천", "Incheon"),
    "daejeon": ("KR", "대전", "Daejeon"),
    "gwangju": ("KR", "광주", "Gwangju"),
    # 일본 (한국에서 비행기로 평균 2시간 내외)
    "tokyo": ("JP", "도쿄", "Tokyo"),
    "osaka": ("JP", "오사카", "Osaka"),
    "kyoto": ("JP", "교토", "Kyoto"),
    "yokohama": ("JP", "요코하마", "Yokohama"),
    "nagoya": ("JP", "나고야", "Nagoya"),
    "fukuoka": ("JP", "후쿠오카", "Fukuoka"),
    "sapporo": ("JP", "삿포로", "Sapporo"),
    "kobe": ("JP", "고베", "Kobe"),
    "sendai": ("JP", "센다이", "Sendai"),
}
# 국가 일반 키워드 → (국가, 도시 KO, 도시 EN)
COUNTRY_MAP = {
    "korea": ("KR", "한국", "Korea"),
    "japan": ("JP", "일본", "Japan"),
}

# find_signals 가 훑을 키워드 목록 (개최장 → 도시 → 국가 순으로 구체적인 것 우선)
KEYWORDS = list(VENUE_MAP) + list(CITY_MAP) + list(COUNTRY_MAP)
# 흔한 오탐 문맥(소속 기관·저자 등)은 신호에서 제외
NEGATIVE = ["university", "univ.", "institute", "kaist", "author", "@"]

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MONTHS = {}
for _i, _m in enumerate(["January", "February", "March", "April", "May", "June",
                         "July", "August", "September", "October", "November",
                         "December"], 1):
    MONTHS[_m.lower()] = _i
    MONTHS[_m[:3].lower()] = _i


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(1_500_000).decode("utf-8", "replace")


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def find_signals(text: str):
    low = text.lower()
    for kw in KEYWORDS:
        for m in re.finditer(re.escape(kw), low):
            # 오탐 필터는 키워드 바로 옆(±25자)만 본다 — 멀리 있는 소속 표기가
            # 정상적인 개최지 발표 문장까지 지우지 않도록
            tight = low[max(0, m.start() - 25): m.end() + 25]
            if any(neg in tight for neg in NEGATIVE):
                continue
            yield kw, text[max(0, m.start() - 90): m.end() + 90].strip()
            break  # 키워드당 첫 유효 문맥 하나면 충분


def pick_location(ctxs):
    """문맥 문자열들에서 (국가, 개최장, 도시 KO, 도시 EN) 를 최선을 다해 추출한다."""
    joined = " ".join(ctxs).lower()
    for vkw, (country, venue, city, city_en) in VENUE_MAP.items():
        if vkw in joined:
            return country, venue, city, city_en
    for ckw, (country, city, city_en) in CITY_MAP.items():
        if ckw in joined:
            return country, "", city, city_en
    for gkw, (country, city, city_en) in COUNTRY_MAP.items():
        if gkw in joined:
            return country, "", city, city_en
    return "KR", "", "한국", "Korea"  # 판단 불가 시 기본값


def _iso(y, mo, d):
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def extract_dates(text):
    """개최일 범위를 최선을 다해 추출한다. 실패하면 ("", "")."""
    t = re.sub(r"\s+", " ", text)
    # "Month D – Month D, YYYY" (달을 넘는 범위) — 더 구체적이므로 먼저 시도
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*[–—-]\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1).lower() in MONTHS and m.group(3).lower() in MONTHS:
        y = int(m.group(5))
        return (_iso(y, MONTHS[m.group(1).lower()], int(m.group(2))),
                _iso(y, MONTHS[m.group(3).lower()], int(m.group(4))))
    # "Month D–D, YYYY" (같은 달 범위)
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s*[–—-]\s*(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        mo, y = MONTHS[m.group(1).lower()], int(m.group(4))
        return _iso(y, mo, int(m.group(2))), _iso(y, mo, int(m.group(3)))
    return "", ""


def build_item(abbr, year, url, ctxs, text):
    country, venue, city, city_en = pick_location(ctxs)
    # 개최일은 문맥에서 먼저, 없으면 페이지 전체에서 시도
    start, end = extract_dates(" ".join(ctxs))
    if not start:
        start, end = extract_dates(text)
    return {
        "abbr": abbr,
        "edition": str(year),
        "year": year,
        "country": country,
        "name": CONF_NAMES.get(abbr, abbr),
        "city": city,
        "cityEn": city_en,
        "venue": venue,
        "start": start,
        "end": end,
        "deadlines": [],
        "site": url,
        "confirmed": False,
        "autoAdded": True,
        "needsReview": True,
    }


def scan(data, tracked, reported):
    """사이트를 훑어 (신규 항목 그룹, 새 신호 id, 에러) 를 돌려준다."""
    today = datetime.date.today()
    years = [today.year, today.year + 1, today.year + 2]
    groups, new_sig, errors = {}, set(), []
    for abbr, tpl in SOURCES:
        for year in years:
            url = tpl.format(year=year)
            try:
                text = visible_text(fetch(url))
            except (urllib.error.URLError, OSError, ValueError) as e:
                errors.append(f"{abbr} {url} — {e}")
                continue
            if (abbr, year) in tracked:
                continue  # 이미 등록된 개최 건
            for kw, ctx in find_signals(text):
                sig_id = f"{abbr}:{year}:{kw}"
                if sig_id in reported:
                    continue
                new_sig.add(sig_id)
                g = groups.setdefault((abbr, year, url), {"kws": [], "ctxs": [], "text": text})
                g["kws"].append(kw)
                g["ctxs"].append(ctx)
    return groups, new_sig, errors


FLAG = {"KR": "🇰🇷", "JP": "🇯🇵"}


def render_pr_body(items, today):
    lines = [
        f"주간 자동 스캔({today.isoformat()})에서 **한국·일본 개최로 보이는 학회 "
        f"{len(items)}건**을 감지해 후보 항목으로 추가했습니다.",
        "",
        "⚠️ 개최지·개최일은 공식 페이지에서 자동 추출한 값이라 부정확할 수 있습니다. "
        "**각 항목을 공식 사이트에서 확인**한 뒤, 맞으면 이 PR 을 머지하세요. "
        "오탐이면 PR 을 닫으면 됩니다(다시 제안되지 않습니다). 값이 틀렸거나 "
        "마감일을 추가하려면 이 브랜치에서 `data/korea_conferences.json` 을 고친 뒤 머지하세요.",
        "",
        "| 학회 | 개최지(자동) | 개최일(자동) | 마감일 | 공식 사이트 |",
        "|---|---|---|---|---|",
    ]
    for it in items:
        flag = FLAG.get(it.get("country", "KR"), "")
        place = (it["city"] + (f" · {it['venue']}" if it["venue"] else "")) or "확인 필요"
        dates = (f"{it['start']} ~ {it['end']}" if it["start"] and it["end"]
                 else "❓ 확인 필요")
        lines.append(f"| {it['abbr']} {it['edition']} | {flag} {place} | {dates} "
                     f"| _미정_ | {it['site']} |")
    lines += [
        "",
        "각 항목은 대시보드에서 **`검토중`** 배지로 표시됩니다. 머지 후 정보를 최종 "
        "확인했으면 `needsReview` 를 `false` 로 바꾸고 마감일을 채워 주세요.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--propose", action="store_true",
                    help="신규 학회를 데이터에 후보로 추가하고 korea.js 를 재생성")
    ap.add_argument("--pr-body", type=pathlib.Path,
                    help="신규 후보가 있을 때 PR 본문(마크다운)을 쓸 경로")
    args = ap.parse_args()

    today = datetime.date.today()
    data = json.loads(SRC.read_text(encoding="utf-8"))
    tracked = {(i["abbr"], int(i["edition"])) for i in data["items"]
               if str(i.get("edition", "")).isdigit()}
    state = (json.loads(STATE.read_text(encoding="utf-8"))
             if STATE.exists() else {"reported": []})
    reported = set(state.get("reported", []))

    groups, new_sig, errors = scan(data, tracked, reported)

    # 새 신호는 항상 상태에 기록해 같은 제안이 반복되지 않게 한다.
    if new_sig:
        reported |= new_sig
        state["reported"] = sorted(reported)
        state["updated"] = today.isoformat()
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    # (abbr, year) 당 후보 항목 하나
    new_items = []
    for (abbr, year, url), g in groups.items():
        if (abbr, year) in tracked:
            continue
        new_items.append(build_item(abbr, year, url, g["ctxs"], g["text"]))
        tracked.add((abbr, year))

    if new_items and args.propose:
        data["items"].extend(new_items)
        # 국가(KR→JP) → 연도 → 시작일 → 약칭 순으로 정렬
        c_order = {"KR": 0, "JP": 1}
        data["items"].sort(key=lambda i: (c_order.get(i.get("country", "KR"), 9),
                                          i["year"], i["start"] or "9999", i["abbr"]))
        data["updated"] = today.isoformat()
        SRC.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_korea.py")],
                       check=True)
        if args.pr_body:
            args.pr_body.write_text(render_pr_body(new_items, today),
                                    encoding="utf-8")

    print(f"scanned {len(SOURCES)} sources × 3 years, "
          f"{len(new_sig)} new signal(s), {len(new_items)} candidate(s), "
          f"{len(errors)} fetch error(s)")
    for it in new_items:
        print(f"  + [{it['country']}] {it['abbr']} {it['edition']} — {it['city']} "
              f"{it['venue']} ({it['start'] or 'date?'})")
    for e in errors:
        print("  skip:", e)


if __name__ == "__main__":
    main()
