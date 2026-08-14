#!/usr/bin/env python3
"""Monthly housekeeping for the "개최지별(한국·일본) 학회 현황" data.

1. 종료된 지 GRACE_DAYS(60일)가 지난 학회를 items 에서 past 로 옮겨 보관한다.
2. docs/assets/korea.js 를 다시 생성한다 (scripts/build_korea.py 재사용).
3. --issue-body PATH 를 주면 월간 점검용 GitHub 이슈 본문(마크다운)을 쓴다.
   (특별 관리 13개 학회의 다음 개최지(한국/일본) 발표 확인 체크리스트 포함)

GitHub Actions (.github/workflows/korea-monthly-check.yml) 가 매월 실행하며,
수동 실행도 가능하다:

  python3 scripts/check_korea.py --issue-body /tmp/body.md
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "korea_conferences.json"

GRACE_DAYS = 60  # 종료 후에도 이 기간 동안은 표에 남겨 둔다

SITE_HINTS = {
    "ICML": "https://icml.cc/",
    "ICLR": "https://iclr.cc/",
    "AAAI": "https://aaai.org/conference/aaai/",
    "NeurIPS": "https://neurips.cc/",
    "IJCAI": "https://www.ijcai.org/future_conferences",
    "CVPR": "https://cvpr.thecvf.com/",
    "ICCV": "https://iccv.thecvf.com/",
    "ECCV": "https://eccv.ecva.net/",
    "ACL": "https://www.aclweb.org/portal/",
    "EMNLP": "https://www.emnlp.org/",
    "NAACL": "https://naacl.org/",
    "ICASSP": "https://signalprocessingsociety.org/conferences-events",
    "INTERSPEECH": "https://isca-speech.org/Upcoming-Interspeech",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue-body", type=pathlib.Path,
                    help="월간 점검 이슈 본문(마크다운)을 쓸 경로")
    args = ap.parse_args()

    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=GRACE_DAYS)
    data = json.loads(SRC.read_text(encoding="utf-8"))

    keep, moved = [], []
    for it in data["items"]:
        end = datetime.date.fromisoformat(it["end"])
        (moved if end < cutoff else keep).append(it)

    if moved:
        data["items"] = keep
        data.setdefault("past", []).extend(moved)
        data["past"].sort(key=lambda i: (i["year"], i["start"], i["abbr"]))
        data["updated"] = today.isoformat()
        SRC.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_korea.py")],
                       check=True)
        print(f"archived {len(moved)} past conference(s): "
              + ", ".join(f"{i['abbr']} {i['edition']}" for i in moved))
    else:
        print("no conferences to archive")

    if args.issue_body:
        flag = {"KR": "🇰🇷", "JP": "🇯🇵"}
        lines = [
            f"매월 자동 생성되는 **한국·일본 개최 학회 데이터 점검** 이슈입니다. ({today.isoformat()} 기준)",
            "",
            "## 현재 등록된 학회",
            "",
            "| 국가 | 학회 | 개최지 | 일정 | 상태 |",
            "|---|---|---|---|---|",
        ]
        for it in sorted(data["items"],
                         key=lambda i: (i.get("country", "KR"), i["start"])):
            end = datetime.date.fromisoformat(it["end"])
            start = datetime.date.fromisoformat(it["start"])
            status = ("종료" if end < today
                      else "진행 중" if start <= today else "예정")
            country = it.get("country", "KR")
            place = it["city"] + (f" · {it['venue']}" if it.get("venue") else "")
            lines.append(f"| {flag.get(country, '')} {country} | {it['abbr']} {it['edition']} "
                         f"| {place} | {it['start']} ~ {it['end']} | {status} |")
        if moved:
            lines += ["", "이번 달 `past` 로 보관 처리: "
                      + ", ".join(f"{i['abbr']} {i['edition']}" for i in moved)]
        lines += [
            "",
            "## 점검 체크리스트 — 특별 관리 대상 13개 학회",
            "",
            "다음 개최지(**한국 또는 일본** 여부)가 새로 발표되었는지 공식 사이트에서 확인해 주세요. "
            "(일본은 한국에서 비행기로 평균 2시간 내외라 출장 부담이 적습니다.)",
            "",
        ]
        tracked = {i["abbr"]: i.get("country", "KR") for i in data["items"]}
        for abbr in data.get("specialWatch", []):
            mark = (f" — **현재 {flag.get(tracked[abbr], '')} 개최 등록됨**"
                    if abbr in tracked else "")
            url = SITE_HINTS.get(abbr, "")
            lines.append(f"- [ ] [{abbr}]({url}){mark}")
        lines += [
            "",
            "새 한국·일본 개최가 발표되면 `data/korea_conferences.json` 의 `items` 에 "
            "(`country`: `KR`/`JP` 포함) 추가하고 `python3 scripts/build_korea.py` 를 실행한 "
            "뒤 커밋해 주세요. (연도별 URL 을 가진 학회는 주간 스캔이 감지하면 `korea-auto` "
            "라벨 PR 을 자동으로 열어 주므로, 그 PR 을 검토·머지하면 됩니다. 위 체크리스트는 "
            "주로 스캔이 어려운 AAAI·IJCAI 같은 단일 페이지 학회를 수동 확인하기 위한 것입니다.)",
        ]
        args.issue_body.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"issue body written: {args.issue_body}")


if __name__ == "__main__":
    main()
